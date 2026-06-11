"""Offline end-to-end proof: ingest recorded fixtures, sieve, enrich,
build an issue, and publish the static site. No API key, no network.

Fixture dates are fixed, so the demo always runs as of 2026-06-10 and is
reproducible byte for byte. All fixture companies are fictional; the
published pages carry a sample-data banner.

Refuses to run if the database already holds live-mode events, so a demo
can never mix fixture data into a real dataset; point RADAR_DB or --db
at a scratch file instead.
"""

import argparse
import sys

from radar import config, db, enrich, ingest, init, issue, publish, sieve, util

DEMO_AS_OF = "2026-06-10"


def _stage(title):
    print()
    print(util.hr(title))


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m radar.demo", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    util.add_common_args(parser, fixtures=False, as_of=False)
    args = parser.parse_args(argv)
    db_args = ["--db", args.db] if args.db else []

    conn = db.connect(args.db)
    db.init_db(conn)
    live = conn.execute(
        "SELECT COUNT(*) c FROM funding_events WHERE source_mode = 'live'"
    ).fetchone()["c"]
    conn.close()
    if live:
        print("demo: %s already holds %d live-mode event(s); refusing to mix "
              "fixture data in. Run with --db /tmp/demo.db instead." %
              (args.db or config.DB_PATH, live))
        return 2

    print("London Seed Radar demo: fixtures only, as of %s." % DEMO_AS_OF)

    _stage("1/6 init")
    init.main(db_args)
    _stage("2/6 ingest --fixtures")
    ingest.main(db_args + ["--fixtures", "--as-of", DEMO_AS_OF])
    _stage("3/6 sieve --fixtures")
    sieve.main(db_args + ["--fixtures", "--as-of", DEMO_AS_OF])
    _stage("4/6 enrich --fixtures")
    enrich.main(db_args + ["--fixtures"])
    _stage("5/6 issue")
    issue.main(db_args + ["--as-of", DEMO_AS_OF])
    _stage("6/6 publish")
    publish.main(db_args)

    _stage("demo complete")
    print("Open docs/index.html in a browser, read "
          "issues/%s/draft-issue.md, then:" % DEMO_AS_OF)
    print("  python -m radar.status")
    print("  python -m radar.todo list")
    return 0


if __name__ == "__main__":
    sys.exit(main())
