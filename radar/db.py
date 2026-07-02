"""SQLite access layer.

Owns the forward-only status flow for funding events:
discovered -> sieved -> enriched -> featured -> published,
with dropped as a terminal branch. Statuses never move backwards.
"""

import datetime
import re
import sqlite3

from radar import config

STATUS_ORDER = ["discovered", "sieved", "enriched", "featured", "published"]
TERMINAL_STATUSES = {"published", "dropped"}


class StatusFlowError(Exception):
    """Raised on any attempt to move a funding event status backwards
    or out of a terminal state."""


def connect(db_path=None):
    path = str(db_path or config.DB_PATH)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn):
    conn.executescript(config.SCHEMA_PATH.read_text())
    conn.commit()


def normalize_name(name):
    """Lowercase, strip punctuation and legal suffixes, collapse spaces.
    'Hedgerow Labs Ltd.' and 'HEDGEROW LABS LIMITED' normalize identically."""
    s = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    s = re.sub(r"\b(ltd|limited|plc|llp|uk)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def advance_status(conn, event_id, new_status, drop_reason=None):
    """Move a funding event forward in the status flow. Forward-only:
    skipping ahead is allowed, moving back or out of a terminal state is not.
    """
    row = conn.execute(
        "SELECT status FROM funding_events WHERE id = ?", (event_id,)
    ).fetchone()
    if row is None:
        raise ValueError("no funding event with id %s" % event_id)
    current = row["status"]

    if current in TERMINAL_STATUSES:
        raise StatusFlowError(
            "event %s is %s (terminal); refusing to move to %s"
            % (event_id, current, new_status)
        )
    if new_status == "dropped":
        if not drop_reason:
            raise StatusFlowError("dropping event %s requires a drop_reason" % event_id)
        conn.execute(
            "UPDATE funding_events SET status = 'dropped', drop_reason = ? WHERE id = ?",
            (drop_reason, event_id),
        )
        return
    if new_status not in STATUS_ORDER:
        raise StatusFlowError("unknown status %r" % new_status)
    if STATUS_ORDER.index(new_status) <= STATUS_ORDER.index(current):
        raise StatusFlowError(
            "event %s: %s -> %s would move the status backwards or repeat it"
            % (event_id, current, new_status)
        )
    conn.execute(
        "UPDATE funding_events SET status = ? WHERE id = ?", (new_status, event_id)
    )


def publish_issue(conn, issue_id):
    """Move an issue draft -> published, the only legal transition, and
    stamp published_at. Idempotent: an already-published issue is left
    untouched and False is returned. The raw-SQL version of this lived in
    publish.py, outside any guard; issues now go through here so the
    forward-only rule has a single owner for both tables."""
    row = conn.execute(
        "SELECT status FROM issues WHERE id = ?", (issue_id,)).fetchone()
    if row is None:
        raise ValueError("no issue with id %s" % issue_id)
    if row["status"] == "published":
        return False
    conn.execute(
        "UPDATE issues SET status = 'published', published_at = ? "
        "WHERE id = ?",
        (datetime.datetime.now().isoformat(timespec="seconds"), issue_id))
    return True


def upsert_company(conn, name, company_number=None, domain=None, **fields):
    """Find or create a company, deduping on company_number, then domain,
    then normalized name. Non-null fields update the existing row."""
    norm = normalize_name(name)
    row = None
    if company_number:
        row = conn.execute(
            "SELECT * FROM companies WHERE company_number = ?", (company_number,)
        ).fetchone()
    if row is None and domain:
        row = conn.execute(
            "SELECT * FROM companies WHERE domain = ?", (domain,)
        ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT * FROM companies WHERE normalized_name = ?", (norm,)
        ).fetchone()

    if row is None:
        cur = conn.execute(
            "INSERT INTO companies (name, normalized_name, company_number, domain) "
            "VALUES (?, ?, ?, ?)",
            (name, norm, company_number, domain),
        )
        company_id = cur.lastrowid
    else:
        company_id = row["id"]
        if company_number and not row["company_number"]:
            conn.execute(
                "UPDATE companies SET company_number = ? WHERE id = ?",
                (company_number, company_id),
            )
        if domain and not row["domain"]:
            conn.execute(
                "UPDATE companies SET domain = ? WHERE id = ?", (domain, company_id)
            )

    updates = {k: v for k, v in fields.items() if v is not None}
    if updates:
        assignments = ", ".join("%s = ?" % k for k in updates)
        conn.execute(
            "UPDATE companies SET %s WHERE id = ?" % assignments,
            list(updates.values()) + [company_id],
        )
    return company_id


def get_company(conn, company_id):
    return conn.execute(
        "SELECT * FROM companies WHERE id = ?", (company_id,)
    ).fetchone()


def event_evidence(conn, event_id):
    return conn.execute(
        "SELECT * FROM evidence WHERE funding_event_id = ? ORDER BY kind", (event_id,)
    ).fetchall()


def add_evidence(conn, event_id, kind, source_name, url, title=None,
                 snippet=None, published_date=None):
    # A missing url is stored as '' rather than NULL: SQLite treats every
    # NULL as distinct in a UNIQUE constraint, so NULL urls would bypass
    # UNIQUE(funding_event_id, kind, url) and duplicate on every re-run.
    conn.execute(
        "INSERT OR IGNORE INTO evidence "
        "(funding_event_id, kind, source_name, url, title, snippet, published_date) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (event_id, kind, source_name, url or "", title, snippet, published_date),
    )
