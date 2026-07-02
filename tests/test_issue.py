"""Issue assembly: the re-run guard (a second draft for the same date must
not strand the previously featured batch), the shortfall note, and the
forward-only wiring. File output is isolated to a temp dir by pointing
config.ISSUES_DIR at it; the DB is a temp file."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from radar import config, db, issue


def _make_enriched(conn, name, event_date, number):
    company_id = db.upsert_company(
        conn, name, company_number=number,
        location_text="1 Test Street, London, EC2A 4PS",
        website="https://example.com/%s" % number,
        website_status="live", one_liner="Builds useful things for tests.",
        one_liner_source="test", headcount_estimate="1-10",
        headcount_source="test", ats_status="none")
    event, _ = __import__("radar.ingest", fromlist=["ingest"]).\
        find_or_create_event(conn, company_id, event_date, "fixture")
    conn.execute("UPDATE funding_events SET stage = 'seed', "
                 "amount_gbp = 1000000 WHERE id = ?", (event,))
    db.add_evidence(conn, event, "press", "UKTN",
                    "https://example.com/press/%s" % number,
                    title="%s raises seed round in London" % name,
                    snippet="%s, a London startup, raised a seed round."
                            % name,
                    published_date=event_date)
    for status in ("sieved", "enriched"):
        db.advance_status(conn, event, status)
    return event


class TestIssueRerunGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db_path = self.tmp / "test.db"
        self.orig_issues_dir = config.ISSUES_DIR
        self.orig_root = config.ROOT
        config.ISSUES_DIR = self.tmp / "issues"
        config.ROOT = self.tmp
        self.addCleanup(setattr, config, "ISSUES_DIR", self.orig_issues_dir)
        self.addCleanup(setattr, config, "ROOT", self.orig_root)
        conn = db.connect(self.db_path)
        db.init_db(conn)
        self.first_event = _make_enriched(conn, "Alphaco", "2026-06-20",
                                          "16010001")
        conn.commit()
        conn.close()

    def run_issue(self):
        return issue.main(["--db", str(self.db_path),
                           "--as-of", "2026-06-29"])

    def test_first_run_features_and_writes_draft(self):
        self.assertEqual(self.run_issue(), 0)
        draft = config.ISSUES_DIR / "2026-06-29" / "draft-issue.md"
        self.assertTrue(draft.exists())
        self.assertIn("Alphaco", draft.read_text())

    def test_rerun_refuses_instead_of_stranding_the_first_batch(self):
        # regression for the audit's M5: run issue, enrich one more company,
        # run issue again for the same date; the second run used to gather
        # only the new company and overwrite the draft, stranding the first
        # batch as permanently 'featured' with the same issue_date
        self.assertEqual(self.run_issue(), 0)
        draft = config.ISSUES_DIR / "2026-06-29" / "draft-issue.md"
        first_draft = draft.read_text()

        conn = db.connect(self.db_path)
        _make_enriched(conn, "Betaco", "2026-06-22", "16010002")
        conn.commit()
        conn.close()

        self.assertEqual(self.run_issue(), 2)
        self.assertEqual(draft.read_text(), first_draft)

        conn = db.connect(self.db_path)
        row = conn.execute(
            "SELECT status, issue_date FROM funding_events WHERE id = ?",
            (self.first_event,)).fetchone()
        conn.close()
        self.assertEqual(row["status"], "featured")
        self.assertEqual(row["issue_date"], "2026-06-29")

    def test_published_issue_refuses_rebuild(self):
        self.assertEqual(self.run_issue(), 0)
        conn = db.connect(self.db_path)
        conn.execute("UPDATE issues SET status = 'published' "
                     "WHERE issue_date = '2026-06-29'")
        conn.commit()
        conn.close()
        self.assertEqual(self.run_issue(), 2)


if __name__ == "__main__":
    unittest.main()
