"""Stage 4: issue. Select the top enriched events for the week (target
set by companies_per_issue in sources.yaml, default 10), render a
per-company research brief plus a draft issue into issues/YYYY-MM-DD/,
advance those events to 'featured', and create the week's human todos.

If fewer companies qualify than the target, the issue features all of
them and says so; it is never padded with unverified entries.

The draft is a DRAFT. The human edits it and owns the final voice;
nothing in this repo can publish or send it.
"""

import argparse
import sys

import jinja2

from radar import config, db, stages, util

WEEKLY_TASKS = [
    ("Edit the draft issue at {path} and finalise the copy; the published "
     "voice must be yours", "before sending"),
    ("Paste the final issue into the newsletter platform and schedule it",
     "publication day"),
    ("Post the issue to LinkedIn from your account", "publication day"),
    ("Send a personal note to each featured founder from your own email "
     "or LinkedIn", "within 2 days of sending"),
    ("Log subscriber count and open rate: python -m radar.metrics log "
     "--subscribers N --open-rate N", "2 days after sending"),
]


def _env():
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(config.TEMPLATES_DIR)),
        trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)


def score(event, evidence_kinds, jobs_count):
    """Corroboration first, hiring signal second."""
    s = 0
    s += 2 if "filing" in evidence_kinds else 0
    s += 1 if "press" in evidence_kinds else 0
    s += 1 if jobs_count else 0
    return s


def gather_featured(conn, limit):
    rows = conn.execute(
        "SELECT * FROM funding_events WHERE status = 'enriched' "
        "ORDER BY event_date DESC").fetchall()
    scored = []
    for event in rows:
        company = db.get_company(conn, event["company_id"])
        evidence = db.event_evidence(conn, event["id"])
        founders = conn.execute(
            "SELECT * FROM founders WHERE company_id = ? ORDER BY name",
            (company["id"],)).fetchall()
        jobs = conn.execute(
            "SELECT * FROM jobs WHERE company_id = ? ORDER BY title",
            (company["id"],)).fetchall()
        entry = {
            "event": dict(event), "company": dict(company),
            "evidence": [dict(e) for e in evidence],
            "founders": [dict(f) for f in founders],
            "jobs": [dict(j) for j in jobs],
            "slug": util.slugify(company["name"]),
            "amount_label": stages.format_amount(event["amount_gbp"]),
        }
        entry["score"] = score(event, {e["kind"] for e in evidence}, len(jobs))
        entry.update(_display_labels(entry))
        scored.append(entry)
    scored.sort(key=lambda e: (e["score"], e["event"]["event_date"]),
                reverse=True)
    return scored[:limit]


def _display_labels(entry):
    """Precomputed strings so the markdown template stays whitespace-safe."""
    founders = []
    for f in entry["founders"]:
        detail = "; ".join(filter(None, [f["role"], f["background"]]))
        founders.append("%s (%s)" % (f["name"], detail) if detail else f["name"])

    company, jobs = entry["company"], entry["jobs"]
    if jobs:
        titles = ", ".join(sorted(j["title"] for j in jobs)[:3])
        hiring = ("%d live role(s) on %s, including %s"
                  % (len(jobs), company["ats_provider"], titles))
    elif company["ats_status"] == "unverifiable":
        hiring = ("job board exists but its public API is disabled; "
                  "hiring unverifiable")
    else:
        hiring = "no public job board found"

    evidence = ", ".join("[%s](%s)" % (e["source_name"], e["url"])
                         for e in entry["evidence"])
    return {"founders_label": ", ".join(founders),
            "hiring_label": hiring, "evidence_label": evidence}


def create_weekly_todos(conn, issue_date, issue_path):
    existing = conn.execute(
        "SELECT COUNT(*) c FROM human_todos WHERE issue_date = ?",
        (str(issue_date),)).fetchone()["c"]
    if existing:
        return 0
    for task, due in WEEKLY_TASKS:
        conn.execute(
            "INSERT INTO human_todos (task, category, due_hint, issue_date) "
            "VALUES (?, 'weekly', ?, ?)",
            (task.format(path=issue_path), due, str(issue_date)))
    return len(WEEKLY_TASKS)


def warn_stale_weeklies(conn, issue_date):
    stale = conn.execute(
        "SELECT * FROM human_todos WHERE category = 'weekly' AND "
        "status = 'pending' AND issue_date < ? ORDER BY issue_date",
        (str(issue_date),)).fetchall()
    if stale:
        print("WARNING: %d weekly todo(s) from previous issues still pending:"
              % len(stale))
        for todo in stale:
            print("  #%d (%s) %s" % (todo["id"], todo["issue_date"],
                                     todo["task"]))
    return len(stale)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m radar.issue", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    util.add_common_args(parser, fixtures=False)
    args = parser.parse_args(argv)
    as_of = util.resolve_as_of(args)

    conn = db.connect(args.db)
    db.init_db(conn)

    existing = conn.execute(
        "SELECT * FROM issues WHERE issue_date = ?", (str(as_of),)).fetchone()
    if existing and existing["status"] == "published":
        print("issue %s is already published; refusing to rebuild it." % as_of)
        return 2

    target = config.companies_per_issue()
    featured = gather_featured(conn, limit=target)
    if not featured:
        print("issue: nothing with status 'enriched'; run the earlier stages first.")
        return 2
    if len(featured) < target:
        print("note: only %d enriched candidate(s); featuring all of them "
              "(target is %d, set in sources.yaml)." % (len(featured), target))

    warn_stale_weeklies(conn, as_of)

    issue_dir = config.ISSUES_DIR / str(as_of)
    briefs_dir = issue_dir / "briefs"
    briefs_dir.mkdir(parents=True, exist_ok=True)
    env = _env()

    for entry in featured:
        brief = env.get_template("brief.md.j2").render(
            entry=entry, issue_date=as_of)
        (briefs_dir / ("%s.md" % entry["slug"])).write_text(brief)

    draft = env.get_template("issue.md.j2").render(
        entries=featured, issue_date=as_of,
        week_label=as_of.strftime("%-d %B %Y"))
    draft_path = issue_dir / "draft-issue.md"
    draft_path.write_text(draft)

    rel_path = str(draft_path.relative_to(config.ROOT))
    if existing:
        conn.execute("UPDATE issues SET path = ? WHERE id = ?",
                     (rel_path, existing["id"]))
    else:
        conn.execute("INSERT INTO issues (issue_date, path) VALUES (?, ?)",
                     (str(as_of), rel_path))
    for entry in featured:
        db.advance_status(conn, entry["event"]["id"], "featured")
        conn.execute("UPDATE funding_events SET issue_date = ? WHERE id = ?",
                     (str(as_of), entry["event"]["id"]))
    created = create_weekly_todos(conn, as_of, rel_path)
    conn.commit()

    print("issue %s: featured %d compan%s" %
          (as_of, len(featured), "y" if len(featured) == 1 else "ies"))
    print("  draft:  %s" % rel_path)
    print("  briefs: %s/" % briefs_dir.relative_to(config.ROOT))
    if created:
        print("  created %d weekly human todos (python -m radar.todo list)"
              % created)
    print("The draft is a starting point. Edit it; the published voice is yours.")
    print("Next: python -m radar.publish")
    return 0


if __name__ == "__main__":
    sys.exit(main())
