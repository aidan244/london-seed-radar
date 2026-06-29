"""One-screen overview: pipeline state, the current issue, pending human
todos, and the latest metrics."""

import argparse
import sys

from radar import config, db, stats, util


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
    counts = stats.pipeline_counts(conn)
    for status in db.STATUS_ORDER + ["dropped"]:
        if counts.get(status):
            print("  %-12s %d" % (status, counts[status]))
    if not counts:
        print("  empty; run python -m radar.ingest (or radar.demo)")

    print()
    issue = stats.current_issue(conn)
    if issue:
        print("Current issue: %s (%s)  %s"
              % (issue["issue_date"], issue["status"], issue["path"]))
    else:
        print("Current issue: none yet")

    print()
    todos = stats.pending_todos(conn)
    print("Pending human todos: %d" % len(todos))
    for todo in todos[:8]:
        print("  #%-3d [%s] %s" % (todo["id"], todo["category"], todo["task"]))
    if len(todos) > 8:
        print("  ... and %d more (python -m radar.todo list)" % (len(todos) - 8))

    print()
    metric = stats.latest_metric(conn)
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
    print("Suggested next step: %s" % stats.next_step_hint(conn, counts, issue))
    return 0


if __name__ == "__main__":
    sys.exit(main())
