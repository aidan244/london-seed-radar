"""Initialise the database and seed the setup checklist of human todos.
Idempotent: safe to run again at any time."""

import argparse
import sys

from radar import config, db, util

SETUP_TODOS = [
    ("Register for a free Companies House API key at "
     "developer.company-information.service.gov.uk and put it in .env as "
     "COMPANIES_HOUSE_API_KEY", "before first live ingest"),
    ("Create the newsletter account (Beehiiv or Substack) and set the "
     "publication name", "before first issue"),
    ("Enable GitHub Pages on this repo: Settings > Pages > deploy from "
     "branch, folder /docs", "before first publish"),
    ("Join at least 3 London startup communities (Slack and WhatsApp "
     "groups) for distribution", "week 1"),
    ("Decide the publication day and time", "week 1"),
]


def seed_setup_todos(conn):
    created = 0
    for task, due in SETUP_TODOS:
        exists = conn.execute(
            "SELECT 1 FROM human_todos WHERE task = ?", (task,)).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO human_todos (task, category, due_hint) "
                "VALUES (?, 'setup', ?)", (task, due))
            created += 1
    return created


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m radar.init", description=__doc__)
    util.add_common_args(parser, fixtures=False, as_of=False)
    args = parser.parse_args(argv)

    conn = db.connect(args.db)
    db.init_db(conn)
    created = seed_setup_todos(conn)
    conn.commit()
    config.ISSUES_DIR.mkdir(exist_ok=True)
    config.DOCS_DIR.mkdir(exist_ok=True)

    print("init: database ready at %s" % (args.db or config.DB_PATH))
    print("  seeded %d setup todo(s)" % created)
    print("Next: python -m radar.todo list, then python -m radar.demo "
          "for an offline end-to-end run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
