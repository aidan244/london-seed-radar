"""Pins radar/todo.py's CLI behaviour against a temp file-backed SQLite
DB (via main(['--db', path, ...])): list on an empty DB, add creates a row
with category and due hint, done flips status and stamps done_at, edit
rewords a task without touching its status, and done on a missing id fails
gracefully (a nonzero return, never a traceback)."""

import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path

from radar import db, todo


class TestTodoCli(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db_path = self.tmp / "test.db"

    def _run(self, argv):
        """Run main() with the temp db, capturing stdout."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = todo.main(["--db", str(self.db_path)] + argv)
        return rc, buf.getvalue()

    def _row(self, todo_id):
        conn = db.connect(self.db_path)
        row = conn.execute("SELECT * FROM human_todos WHERE id = ?",
                           (todo_id,)).fetchone()
        conn.close()
        return row

    def test_list_on_empty_db(self):
        rc, out = self._run(["list"])
        self.assertEqual(rc, 0)
        self.assertIn("No pending todos.", out)

    def test_add_creates_row_with_category_and_due(self):
        rc, out = self._run(["add", "Register Companies House API key",
                             "--category", "setup", "--due", "before launch"])
        self.assertEqual(rc, 0)
        self.assertIn("Added #1 (setup)", out)

        row = self._row(1)
        self.assertIsNotNone(row)
        self.assertEqual(row["task"], "Register Companies House API key")
        self.assertEqual(row["category"], "setup")
        self.assertEqual(row["due_hint"], "before launch")
        self.assertEqual(row["status"], "pending")

    def test_add_defaults_to_growth_category_with_no_due(self):
        rc, _ = self._run(["add", "Post to LinkedIn"])
        self.assertEqual(rc, 0)
        row = self._row(1)
        self.assertEqual(row["category"], "growth")
        self.assertIsNone(row["due_hint"])

    def test_list_after_add_shows_the_pending_task(self):
        self._run(["add", "Join the founder Slack", "--category", "growth"])
        rc, out = self._run(["list"])
        self.assertEqual(rc, 0)
        self.assertIn("Join the founder Slack", out)
        self.assertIn("1 pending.", out)

    def test_done_flips_status_and_stamps_done_at(self):
        self._run(["add", "Enable GitHub Pages", "--category", "setup"])
        row = self._row(1)
        self.assertIsNone(row["done_at"])

        rc, out = self._run(["done", "1"])
        self.assertEqual(rc, 0)
        self.assertIn("Done: #1 Enable GitHub Pages", out)

        row = self._row(1)
        self.assertEqual(row["status"], "done")
        self.assertIsNotNone(row["done_at"])

    def test_done_twice_is_a_no_op_second_time(self):
        self._run(["add", "Create the newsletter account"])
        self._run(["done", "1"])
        first_done_at = self._row(1)["done_at"]

        rc, out = self._run(["done", "1"])
        self.assertEqual(rc, 0)
        self.assertIn("already done", out)
        self.assertEqual(self._row(1)["done_at"], first_done_at)

    def test_edit_rewords_a_task_and_preserves_pending_status(self):
        self._run(["add", "Message founders", "--category", "growth",
                  "--due", "this week"])
        rc, out = self._run(["edit", "1", "Message founders on LinkedIn"])
        self.assertEqual(rc, 0)
        self.assertIn("Edited #1:", out)

        row = self._row(1)
        self.assertEqual(row["task"], "Message founders on LinkedIn")
        self.assertEqual(row["status"], "pending")
        # --due was not passed, so the original due hint is untouched
        self.assertEqual(row["due_hint"], "this week")

    def test_edit_preserves_done_status(self):
        self._run(["add", "Log metrics"])
        self._run(["done", "1"])
        rc, _ = self._run(["edit", "1", "Log metrics in the dashboard"])
        self.assertEqual(rc, 0)

        row = self._row(1)
        self.assertEqual(row["task"], "Log metrics in the dashboard")
        self.assertEqual(row["status"], "done")

    def test_edit_with_due_updates_due_hint(self):
        self._run(["add", "Message founders", "--due", "this week"])
        self._run(["edit", "1", "Message founders warmly", "--due", "today"])
        row = self._row(1)
        self.assertEqual(row["task"], "Message founders warmly")
        self.assertEqual(row["due_hint"], "today")

    def test_done_on_missing_id_fails_gracefully(self):
        rc, out = self._run(["done", "999"])
        self.assertEqual(rc, 2)
        self.assertIn("No todo #999.", out)

    def test_edit_on_missing_id_fails_gracefully(self):
        rc, out = self._run(["edit", "999", "does not exist"])
        self.assertEqual(rc, 2)
        self.assertIn("No todo #999.", out)


if __name__ == "__main__":
    unittest.main()
