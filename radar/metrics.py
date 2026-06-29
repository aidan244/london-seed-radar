"""Metrics: the numbers that matter, logged manually by the human and
never estimated by code. They will end up on a CV; keep them honest.

  python -m radar.metrics log --subscribers 42 --open-rate 51.5 \
      [--replies 2] [--revenue 0] [--notes "..."] [--date YYYY-MM-DD]
  python -m radar.metrics show
"""

import argparse
import datetime
import sys

from radar import db, util


def cmd_log(conn, args):
    date = args.date or datetime.date.today().isoformat()
    conn.execute(
        "INSERT INTO metrics (date, subscribers, open_rate, "
        "replies_from_founders, revenue_gbp, notes) VALUES (?, ?, ?, ?, ?, ?)",
        (date, args.subscribers, args.open_rate, args.replies,
         args.revenue, args.notes))
    conn.commit()
    print("Logged metrics for %s." % date)
    return 0


def cmd_show(conn):
    rows = conn.execute("SELECT * FROM metrics ORDER BY date").fetchall()
    if not rows:
        print("No metrics logged yet. After each issue:")
        print("  python -m radar.metrics log --subscribers N --open-rate N")
        return 0
    print("%-12s %11s %9s %8s %11s  %s"
          % ("date", "subscribers", "open rate", "replies", "revenue", "notes"))
    for r in rows:
        print("%-12s %11s %9s %8s %11s  %s" % (
            r["date"],
            r["subscribers"] if r["subscribers"] is not None else "-",
            ("%.1f%%" % r["open_rate"]) if r["open_rate"] is not None else "-",
            r["replies_from_founders"] if r["replies_from_founders"] is not None else "-",
            ("£%.2f" % r["revenue_gbp"]) if r["revenue_gbp"] is not None else "-",
            r["notes"] or ""))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m radar.metrics", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    util.add_common_args(parser, fixtures=False, as_of=False)
    sub = parser.add_subparsers(dest="verb")
    p_log = sub.add_parser("log", help="log this issue's numbers")
    p_log.add_argument("--date", default=None)
    p_log.add_argument("--subscribers", type=int, default=None)
    p_log.add_argument("--open-rate", type=float, default=None,
                       help="percentage, e.g. 51.5")
    p_log.add_argument("--replies", type=int, default=None,
                       help="replies from founders")
    p_log.add_argument("--revenue", type=float, default=None,
                       help="revenue in GBP")
    p_log.add_argument("--notes", default=None)
    sub.add_parser("show", help="show all logged metrics")
    args = parser.parse_args(argv)

    conn = db.connect(args.db)
    db.init_db(conn)
    if args.verb == "log":
        return cmd_log(conn, args)
    return cmd_show(conn)


if __name__ == "__main__":
    sys.exit(main())
