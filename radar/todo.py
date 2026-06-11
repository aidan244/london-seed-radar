"""The human todo tracker: the canonical list of steps only a human can
do. The pipeline gates on it; treat it as a first-class feature.

  python -m radar.todo list [--all]
  python -m radar.todo done <id>
  python -m radar.todo add "task" [--category setup|weekly|growth] [--due "hint"]
  python -m radar.todo edit <id> "reworded task"
"""

import argparse
import datetime
import sys

from radar import db, util

CATEGORY_ORDER = {"setup": 0, "weekly": 1, "growth": 2}


def cmd_list(conn, show_all):
    where = "" if show_all else "WHERE status = 'pending'"
    rows = conn.execute(
        "SELECT * FROM human_todos %s ORDER BY status, category, id" % where
    ).fetchall()
    if not rows:
        print("No %stodos. Add one: python -m radar.todo add \"task\""
              % ("" if show_all else "pending "))
        return
    rows = sorted(rows, key=lambda r: (r["status"] != "pending",
                                       CATEGORY_ORDER.get(r["category"], 9),
                                       r["id"]))
    current = None
    for row in rows:
        header = "%s, %s" % (row["category"], row["status"])
        if header != current:
            current = header
            print("\n%s:" % header)
        due = " (due: %s)" % row["due_hint"] if row["due_hint"] else ""
        issue = " [issue %s]" % row["issue_date"] if row["issue_date"] else ""
        print("  #%-3d %s%s%s" % (row["id"], row["task"], due, issue))
    pending = sum(1 for r in rows if r["status"] == "pending")
    print("\n%d pending." % pending)


def cmd_done(conn, todo_id):
    row = conn.execute("SELECT * FROM human_todos WHERE id = ?",
                       (todo_id,)).fetchone()
    if row is None:
        print("No todo #%s." % todo_id)
        return 2
    if row["status"] == "done":
        print("#%s is already done." % todo_id)
        return 0
    conn.execute(
        "UPDATE human_todos SET status = 'done', done_at = ? WHERE id = ?",
        (datetime.date.today().isoformat(), todo_id))
    conn.commit()
    print("Done: #%d %s" % (row["id"], row["task"]))
    return 0


def cmd_edit(conn, todo_id, task):
    """Reword a todo when the human redefines the step; marking it done
    when it was not done would be dishonest, and history stays in git
    and HANDOVER.md."""
    row = conn.execute("SELECT * FROM human_todos WHERE id = ?",
                       (todo_id,)).fetchone()
    if row is None:
        print("No todo #%s." % todo_id)
        return 2
    conn.execute("UPDATE human_todos SET task = ? WHERE id = ?",
                 (task, todo_id))
    conn.commit()
    print("Edited #%d:" % row["id"])
    print("  was: %s" % row["task"])
    print("  now: %s" % task)
    return 0


def cmd_add(conn, task, category, due):
    cur = conn.execute(
        "INSERT INTO human_todos (task, category, due_hint) VALUES (?, ?, ?)",
        (task, category, due))
    conn.commit()
    print("Added #%d (%s): %s" % (cur.lastrowid, category, task))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m radar.todo", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    util.add_common_args(parser, fixtures=False, as_of=False)
    sub = parser.add_subparsers(dest="verb")
    p_list = sub.add_parser("list", help="show todos")
    p_list.add_argument("--all", action="store_true", help="include done")
    p_done = sub.add_parser("done", help="mark a todo done")
    p_done.add_argument("id", type=int)
    p_add = sub.add_parser("add", help="add a todo")
    p_add.add_argument("task")
    p_add.add_argument("--category", default="growth",
                       choices=["setup", "weekly", "growth"])
    p_add.add_argument("--due", default=None, help="free-text due hint")
    p_edit = sub.add_parser("edit", help="reword a todo")
    p_edit.add_argument("id", type=int)
    p_edit.add_argument("task")
    args = parser.parse_args(argv)

    conn = db.connect(args.db)
    db.init_db(conn)
    if args.verb == "done":
        return cmd_done(conn, args.id)
    if args.verb == "edit":
        return cmd_edit(conn, args.id, args.task)
    if args.verb == "add":
        return cmd_add(conn, args.task, args.category, args.due)
    cmd_list(conn, getattr(args, "all", False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
