"""Pins radar.demo's live-data refusal guard: the fix for the 2026-06-13
incident (see MISTAKES.md) where `python -m radar.demo --db /tmp/dash.db`
overwrote the repo's working issues/ and docs/ trees. --db only redirects
the SQLite file; demo.main() itself refuses outright, before running any
pipeline stage, if the database it is pointed at already holds any
source_mode='live' funding event, so fixture data can never get mixed
into a real dataset by an accidental demo run.

This test only pins the guard (the point of the regression). It does not
exercise the happy path (fixtures-only run), which regenerates real
artifacts and is out of scope here; config paths are isolated to a temp
dir regardless, the same way tests/test_issue.py does, so nothing lands
in the repo even if the guard were broken by a future change."""

import shutil
import tempfile
import unittest
from io import StringIO
from contextlib import redirect_stdout
from pathlib import Path

from radar import config, db, demo


def _seed_live_event(db_path):
    conn = db.connect(db_path)
    db.init_db(conn)
    company_id = db.upsert_company(
        conn, "Liveco", company_number="16099001",
        website="https://liveco.example", website_status="live")
    conn.execute(
        "INSERT INTO funding_events (company_id, event_date, source_mode) "
        "VALUES (?, ?, ?)",
        (company_id, "2026-06-15", "live"))
    conn.commit()
    conn.close()


class TestDemoRefusesLiveData(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db_path = self.tmp / "live.db"

        # Isolate every artifact path to the temp dir, exactly like
        # tests/test_issue.py, so a broken guard cannot write into the
        # repo's real issues/ or docs/ trees during this test.
        self.orig_root = config.ROOT
        self.orig_issues_dir = config.ISSUES_DIR
        self.orig_docs_dir = config.DOCS_DIR
        config.ROOT = self.tmp
        config.ISSUES_DIR = self.tmp / "issues"
        config.DOCS_DIR = self.tmp / "docs"
        self.addCleanup(setattr, config, "ROOT", self.orig_root)
        self.addCleanup(setattr, config, "ISSUES_DIR", self.orig_issues_dir)
        self.addCleanup(setattr, config, "DOCS_DIR", self.orig_docs_dir)

        _seed_live_event(self.db_path)

    def test_returns_nonzero_instead_of_running_the_pipeline(self):
        out = StringIO()
        with redirect_stdout(out):
            result = demo.main(["--db", str(self.db_path)])
        self.assertEqual(result, 2)
        self.assertIn("already holds", out.getvalue())
        self.assertIn("live-mode event", out.getvalue())

    def test_writes_nothing_to_issues_or_docs_dirs(self):
        demo.main(["--db", str(self.db_path)])
        self.assertFalse(config.ISSUES_DIR.exists(),
                         "guard must return before any stage writes issues/")
        self.assertFalse(config.DOCS_DIR.exists(),
                         "guard must return before any stage writes docs/")

    def test_does_not_mutate_the_seeded_event(self):
        # The guard only reads; a re-run must find the same single live
        # event and refuse again, not double-count or alter it.
        demo.main(["--db", str(self.db_path)])
        conn = db.connect(self.db_path)
        rows = conn.execute(
            "SELECT status, source_mode FROM funding_events").fetchall()
        conn.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "discovered")
        self.assertEqual(rows[0]["source_mode"], "live")

    def test_refuses_again_on_a_second_run(self):
        first = demo.main(["--db", str(self.db_path)])
        second = demo.main(["--db", str(self.db_path)])
        self.assertEqual(first, 2)
        self.assertEqual(second, 2)


if __name__ == "__main__":
    unittest.main()
