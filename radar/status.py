"""One-screen overview: pipeline state, the current issue, pending human
todos, and the latest metrics."""

import argparse
import sys

from radar import config, db, util


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m radar.status", description=__doc__)
    util.add_common_args(parser, fixtures=False, as_of=False)
    args = parser.parse_args(argv)

    conn = db.connect(args.db)
    db.init_db(conn)

    print("London Seed Radar status  (db: %s)" % (args.db or config.DB_PATH))
    print()

    print("Pipeline (funding events by status):")
    counts = {r["status"]: r["c"] for r in conn.execute(
        "SELECT status, COUNT(*) c FROM funding_events GROUP BY status")}
    for status in db.STATUS_ORDER + ["dropped"]:
        if counts.get(status):
            print("  %-12s %d" % (status, counts[status]))
    if not counts:
        print("  empty; run python -m radar.ingest (or radar.demo)")

    print()
    issue = conn.execute(
        "SELECT * FROM issues ORDER BY issue_date DESC LIMIT 1").fetchone()
    if issue:
        print("Current issue: %s (%s)  %s"
              % (issue["issue_date"], issue["status"], issue["path"]))
    else:
        print("Current issue: none yet")

    print()
    todos = conn.execute(
        "SELECT * FROM human_todos WHERE status = 'pending' "
        "ORDER BY CASE category WHEN 'setup' THEN 0 WHEN 'weekly' THEN 1 "
        "ELSE 2 END, id").fetchall()
    print("Pending human todos: %d" % len(todos))
    for todo in todos[:8]:
        print("  #%-3d [%s] %s" % (todo["id"], todo["category"], todo["task"]))
    if len(todos) > 8:
        print("  ... and %d more (python -m radar.todo list)" % (len(todos) - 8))

    print()
    metric = conn.execute(
        "SELECT * FROM metrics ORDER BY date DESC LIMIT 1").fetchone()
    if metric:
        print("Latest metrics (%s): %s subscribers, %s open rate"
              % (metric["date"],
                 metric["subscribers"] if metric["subscribers"] is not None else "?",
                 ("%.1f%%" % metric["open_rate"])
                 if metric["open_rate"] is not None else "?"))
    else:
        print("Latest metrics: none logged yet "
              "(python -m radar.metrics log ... after each issue)")

    print()
    if not counts:
        hint = "python -m radar.demo for an offline proof, then the setup todos"
    elif counts.get("discovered"):
        hint = "python -m radar.sieve"
    elif counts.get("sieved"):
        hint = "python -m radar.enrich"
    elif counts.get("enriched"):
        hint = "python -m radar.issue"
    elif issue and issue["status"] == "draft":
        hint = "edit the draft, then python -m radar.publish"
    else:
        hint = "python -m radar.ingest for the next weekly cycle"
    print("Suggested next step: %s" % hint)
    return 0


if __name__ == "__main__":
    sys.exit(main())
