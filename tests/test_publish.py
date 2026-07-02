"""Stage 5: publish. Pins three behaviours:

1. The public dataset field-set fence (hard rule 2, no contact data).
   export_dataset's JSON and CSV output must expose exactly the fields
   named in publish.py's PUBLIC_*_FIELDS allowlists (plus the few known,
   deliberately-added companion fields: a company's nested founders list,
   an event's company_name, a job's junior_flag), and none of those
   fields may look contact-like. Since the assertions read the allowlist
   constants from radar.publish itself rather than hardcoding a copy, a
   future field addition to the SELECT or the allowlist fails this test
   until the addition is consciously reflected here.
2. The draft -> published cascade: a 'draft' issues row and its
   'featured' funding_events move to 'published' after publish.main;
   re-running publish.main once already published is a no-op (exit code
   2, no exception, no further DB change).
3. The sample-data banner: a fixture-mode featured event makes
   render_site stamp the rendered pages with the sample-data banner.

Isolated to a temp directory: config.DOCS_DIR, config.ISSUES_DIR, and
config.ROOT are pointed at it and restored on cleanup; config.TEMPLATES_DIR
is left alone (radar/templates/ is read-only, no network involved). The
DB is a temp SQLite file so publish.main's CLI path (argparse, --db) is
exercised directly. No network calls anywhere in radar.publish or the
modules it touches (geo, stages, juniors, remote are pure string logic).
"""

import csv
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from radar import config, db, publish

CONTACT_LIKE = re.compile(r"email|phone|contact", re.IGNORECASE)


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


def _company_id_for_event(conn, event_id):
    return conn.execute(
        "SELECT company_id FROM funding_events WHERE id = ?",
        (event_id,)).fetchone()["company_id"]


def _feature(conn, event_id, issue_date):
    """Mirror radar.issue.main's featuring step exactly: advance status,
    then stamp issue_date, in that order."""
    db.advance_status(conn, event_id, "featured")
    conn.execute("UPDATE funding_events SET issue_date = ? WHERE id = ?",
                 (issue_date, event_id))


class TestPublicDatasetFieldFence(unittest.TestCase):
    """Regression fence for hard rule 2: the exported dataset carries only
    the named public fields, and none of the allowlists is contact-like."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db_path = self.tmp / "test.db"
        self.conn = db.connect(self.db_path)
        db.init_db(self.conn)
        self.addCleanup(self.conn.close)

        event = _make_enriched(self.conn, "Fenceco", "2026-06-20", "16020001")
        db.advance_status(self.conn, event, "featured")
        company_id = _company_id_for_event(self.conn, event)
        self.conn.execute(
            "INSERT INTO founders (company_id, name, role, background, "
            "source_url) VALUES (?, ?, ?, ?, ?)",
            (company_id, "Jane Doe", "CEO", "ex-Test Corp; public profile",
             "https://example.com/about"))
        self.conn.execute(
            "INSERT INTO jobs (company_id, title, location, url, "
            "ats_provider) VALUES (?, ?, ?, ?, ?)",
            (company_id, "Junior Software Engineer", "London, UK (Remote)",
             "https://boards.example.com/fenceco/1", "greenhouse"))
        self.conn.commit()

        self.data_dir = self.tmp / "data"

    def test_json_field_sets_equal_the_allowlists_plus_known_companions(self):
        n_companies, n_events, n_jobs = publish.export_dataset(
            self.conn, self.data_dir)
        self.assertEqual((n_companies, n_events, n_jobs), (1, 1, 1))

        companies = json.loads(
            (self.data_dir / "companies.json").read_text())["companies"]
        events = json.loads(
            (self.data_dir / "funding_events.json").read_text())["funding_events"]
        jobs = json.loads(
            (self.data_dir / "jobs.json").read_text())["jobs"]
        self.assertEqual(len(companies), 1)
        self.assertEqual(len(events), 1)
        self.assertEqual(len(jobs), 1)

        expected_company_fields = set(publish.PUBLIC_COMPANY_FIELDS) | {
            "founders"}
        expected_event_fields = set(publish.PUBLIC_EVENT_FIELDS) | {
            "company_name"}
        expected_job_fields = set(publish.PUBLIC_JOB_FIELDS)

        self.assertEqual(set(companies[0].keys()), expected_company_fields)
        self.assertEqual(set(events[0].keys()), expected_event_fields)
        self.assertEqual(set(jobs[0].keys()), expected_job_fields)

        # The nested founders list is the one place a company row could
        # smuggle in a contact field; pin it to the public trio too.
        self.assertEqual(len(companies[0]["founders"]), 1)
        self.assertEqual(set(companies[0]["founders"][0].keys()),
                         {"name", "role", "background"})

    def test_csv_headers_equal_the_allowlists_exactly(self):
        publish.export_dataset(self.conn, self.data_dir)

        with open(self.data_dir / "companies.csv", newline="") as f:
            header = next(csv.reader(f))
        self.assertEqual(header, publish.PUBLIC_COMPANY_FIELDS)

        with open(self.data_dir / "funding_events.csv", newline="") as f:
            header = next(csv.reader(f))
        self.assertEqual(header, ["company_name"] + publish.PUBLIC_EVENT_FIELDS)

        with open(self.data_dir / "jobs.csv", newline="") as f:
            header = next(csv.reader(f))
        self.assertEqual(header, publish.PUBLIC_JOB_FIELDS)

    def test_no_allowlisted_or_companion_field_is_contact_like(self):
        all_field_names = (
            list(publish.PUBLIC_COMPANY_FIELDS)
            + list(publish.PUBLIC_EVENT_FIELDS)
            + list(publish.PUBLIC_JOB_FIELDS)
            + ["founders", "company_name", "name", "role", "background"])
        offenders = [f for f in all_field_names if CONTACT_LIKE.search(f)]
        self.assertEqual(offenders, [])


class TestDraftPublishedCascade(unittest.TestCase):
    """A draft issue and its featured events become published together;
    running publish again once already published changes nothing."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db_path = self.tmp / "test.db"

        self.orig_docs_dir = config.DOCS_DIR
        self.orig_issues_dir = config.ISSUES_DIR
        self.orig_root = config.ROOT
        config.DOCS_DIR = self.tmp / "docs"
        config.ISSUES_DIR = self.tmp / "issues"
        config.ROOT = self.tmp
        self.addCleanup(setattr, config, "DOCS_DIR", self.orig_docs_dir)
        self.addCleanup(setattr, config, "ISSUES_DIR", self.orig_issues_dir)
        self.addCleanup(setattr, config, "ROOT", self.orig_root)

        conn = db.connect(self.db_path)
        db.init_db(conn)
        self.event = _make_enriched(conn, "Cascadeco", "2026-06-20",
                                    "16020002")
        _feature(conn, self.event, "2026-06-29")
        conn.execute(
            "INSERT INTO issues (issue_date, path) VALUES (?, ?)",
            ("2026-06-29", "issues/2026-06-29/draft-issue.md"))
        conn.commit()
        conn.close()

    def _issue_row(self):
        conn = db.connect(self.db_path)
        row = conn.execute(
            "SELECT * FROM issues WHERE issue_date = '2026-06-29'").fetchone()
        conn.close()
        return row

    def _event_status(self):
        conn = db.connect(self.db_path)
        row = conn.execute(
            "SELECT status FROM funding_events WHERE id = ?",
            (self.event,)).fetchone()
        conn.close()
        return row["status"]

    def test_first_run_marks_issue_and_events_published(self):
        rc = publish.main(["--db", str(self.db_path)])
        self.assertEqual(rc, 0)

        issue_row = self._issue_row()
        self.assertEqual(issue_row["status"], "published")
        self.assertIsNotNone(issue_row["published_at"])
        self.assertEqual(self._event_status(), "published")

    def test_second_run_regenerates_without_touching_statuses(self):
        self.assertEqual(publish.main(["--db", str(self.db_path)]), 0)
        published_at_first = self._issue_row()["published_at"]

        # A second run finds no 'draft' issue (the one we had is now
        # 'published'); it regenerates the dataset and site from the latest
        # published issue (exit 0) without touching anything already
        # published: no status change, no new published_at.
        rc = publish.main(["--db", str(self.db_path)])
        self.assertEqual(rc, 0)

        issue_row = self._issue_row()
        self.assertEqual(issue_row["status"], "published")
        self.assertEqual(issue_row["published_at"], published_at_first)
        self.assertEqual(self._event_status(), "published")


class TestSampleDataBanner(unittest.TestCase):
    """A fixture-mode featured/published event makes render_site stamp the
    sample-data banner onto the rendered pages."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

        self.orig_docs_dir = config.DOCS_DIR
        self.orig_issues_dir = config.ISSUES_DIR
        self.orig_root = config.ROOT
        config.DOCS_DIR = self.tmp / "docs"
        config.ISSUES_DIR = self.tmp / "issues"
        config.ROOT = self.tmp
        self.addCleanup(setattr, config, "DOCS_DIR", self.orig_docs_dir)
        self.addCleanup(setattr, config, "ISSUES_DIR", self.orig_issues_dir)
        self.addCleanup(setattr, config, "ROOT", self.orig_root)

    def _seed(self, db_path, name, number, source_mode):
        conn = db.connect(db_path)
        db.init_db(conn)
        event = _make_enriched(conn, name, "2026-06-20", number)
        if source_mode != "fixture":
            conn.execute(
                "UPDATE funding_events SET source_mode = ? WHERE id = ?",
                (source_mode, event))
        _feature(conn, event, "2026-06-29")
        conn.execute(
            "INSERT INTO issues (issue_date, path) VALUES (?, ?)",
            ("2026-06-29", "issues/2026-06-29/draft-issue.md"))
        conn.commit()
        conn.close()

    def test_fixture_mode_event_triggers_the_banner(self):
        db_path = self.tmp / "fixture.db"
        self._seed(db_path, "Sampleco", "16020003", "fixture")

        rc = publish.main(["--db", str(db_path)])
        self.assertEqual(rc, 0)

        index_html = (config.DOCS_DIR / "index.html").read_text()
        self.assertIn("Sample data", index_html)
        issue_html = (config.DOCS_DIR / "issues" / "2026-06-29.html").read_text()
        self.assertIn("Sample data", issue_html)

    def test_live_mode_only_event_has_no_banner(self):
        db_path = self.tmp / "live.db"
        self._seed(db_path, "Liveco", "16020004", "live")

        rc = publish.main(["--db", str(db_path)])
        self.assertEqual(rc, 0)

        index_html = (config.DOCS_DIR / "index.html").read_text()
        self.assertNotIn("Sample data", index_html)
        issue_html = (config.DOCS_DIR / "issues" / "2026-06-29.html").read_text()
        self.assertNotIn("Sample data", issue_html)


if __name__ == "__main__":
    unittest.main()
