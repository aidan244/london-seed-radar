"""Shared read-only aggregations over the working database.

Both radar.status (the terminal overview) and radar.dashboard (the local
HTML control room) read the same numbers from here, so the two views
never drift apart. Every function takes an open connection, only reads,
and never commits.
"""

from radar import db


def pipeline_counts(conn):
    """Funding events grouped by status: {status: count}. Statuses with
    no rows are absent from the dict."""
    return {r["status"]: r["c"] for r in conn.execute(
        "SELECT status, COUNT(*) c FROM funding_events GROUP BY status")}


def current_issue(conn):
    """The most recent issue as a dict, or None."""
    row = conn.execute(
        "SELECT * FROM issues ORDER BY issue_date DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def pending_todos(conn):
    """Pending human todos, ordered setup, issue, growth, then id."""
    rows = conn.execute(
        "SELECT * FROM human_todos WHERE status = 'pending' "
        "ORDER BY CASE category WHEN 'setup' THEN 0 WHEN 'issue' THEN 1 "
        "ELSE 2 END, id").fetchall()
    return [dict(r) for r in rows]


def all_todos(conn):
    """Every human todo, pending and done, in the same category order."""
    rows = conn.execute(
        "SELECT * FROM human_todos "
        "ORDER BY CASE category WHEN 'setup' THEN 0 WHEN 'issue' THEN 1 "
        "ELSE 2 END, status, id").fetchall()
    return [dict(r) for r in rows]


def latest_metric(conn):
    """The most recent metrics row as a dict, or None."""
    row = conn.execute(
        "SELECT * FROM metrics ORDER BY date DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def metrics_series(conn):
    """All metrics rows oldest first, for a time series."""
    rows = conn.execute(
        "SELECT date, subscribers, open_rate, replies_from_founders, "
        "revenue_gbp FROM metrics ORDER BY date").fetchall()
    return [dict(r) for r in rows]


def drop_reasons(conn):
    """Dropped events grouped by the leading gate label (the text before
    the first colon), most common first: [{reason, count}]."""
    rows = conn.execute(
        "SELECT drop_reason, COUNT(*) c FROM funding_events "
        "WHERE status = 'dropped' AND drop_reason IS NOT NULL "
        "GROUP BY drop_reason").fetchall()
    grouped = {}
    for r in rows:
        gate = r["drop_reason"].split(":", 1)[0].strip() or "other"
        grouped[gate] = grouped.get(gate, 0) + r["c"]
    return [{"reason": gate, "count": count}
            for gate, count in sorted(grouped.items(),
                                      key=lambda kv: kv[1], reverse=True)]


def next_step_hint(conn, counts=None, issue=None):
    """The suggested next command, identical to the one radar.status
    prints. Pass counts and issue to avoid re-querying."""
    counts = counts if counts is not None else pipeline_counts(conn)
    issue = issue if issue is not None else current_issue(conn)
    if not counts:
        return "python -m radar.demo for an offline proof, then the setup todos"
    if counts.get("discovered"):
        return "python -m radar.sieve"
    if counts.get("sieved"):
        return "python -m radar.enrich"
    if counts.get("enriched"):
        return "python -m radar.issue"
    if issue and issue["status"] == "draft":
        return "edit the draft, then python -m radar.publish"
    return "python -m radar.ingest for the next issue cycle"
