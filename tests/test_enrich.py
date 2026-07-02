"""Curated live-mode enrichment overrides. A file under enrichment/ is read
in every mode and wins over both the recorded test fixtures and the
auto-derived fallback. No network: ATS probing is stubbed and curated
one-liners skip the homepage fetch."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from radar import config, db, enrich


class TestCuratedEnrichment(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.enrich_dir = Path(self.tmp) / "enrichment"
        self.enrich_dir.mkdir()
        # Point the loader at the temp dir, then restore it.
        orig_dir = config.ENRICHMENT_DIR
        config.ENRICHMENT_DIR = self.enrich_dir
        self.addCleanup(setattr, config, "ENRICHMENT_DIR", orig_dir)
        # Keep enrich offline: never probe live ATS endpoints.
        orig_discover = enrich._discover_ats
        enrich._discover_ats = lambda company, fixtures: (None, None, None)
        self.addCleanup(setattr, enrich, "_discover_ats", orig_discover)

        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        self.addCleanup(self.conn.close)

    def _company(self, number="15396489", name="Conduct", website=None):
        cid = db.upsert_company(self.conn, name, company_number=number,
                                website=website)
        return db.get_company(self.conn, cid)

    def _write_curated(self, number, data):
        (self.enrich_dir / ("%s.json" % number)).write_text(json.dumps(data))

    def test_curated_overrides_applied_in_live(self):
        """With fixtures=False, a curated file's one-liner, headcount, and
        founders land on the company row."""
        self._write_curated("15396489", {
            "one_liner": "Plain rewritten description.",
            "one_liner_source": "company site (verified 2026-06-29)",
            "headcount_estimate": "11-25",
            "headcount_source": "Clay (LinkedIn-derived), 2026-06-29",
            "founders": [{"name": "Jane Doe", "role": "CEO",
                          "background": "ex-Palantir; public profile",
                          "source_url": "https://conduct.ai/about"}],
        })
        company = self._company()
        enrich.enrich_company(self.conn, company, [], fixtures=False)

        row = db.get_company(self.conn, company["id"])
        self.assertEqual(row["one_liner"], "Plain rewritten description.")
        self.assertEqual(row["one_liner_source"],
                         "company site (verified 2026-06-29)")
        self.assertEqual(row["headcount_estimate"], "11-25")
        founders = self.conn.execute(
            "SELECT name, role, background FROM founders WHERE company_id = ?",
            (company["id"],)).fetchall()
        self.assertEqual([(f["name"], f["role"]) for f in founders],
                         [("Jane Doe", "CEO")])

    def test_curated_wins_over_fixture(self):
        """Under --fixtures, the curated file beats the recorded fixture on a
        shared key. 16012001 has a recorded enrichment fixture."""
        self._write_curated("16012001", {
            "one_liner": "Curated one-liner that must win.",
            "ats": None,  # neutralise the fixture's ATS so no fetch happens
        })
        company = self._company(number="16012001", name="Hedgerow Labs")
        enrich.enrich_company(self.conn, company, [], fixtures=True)

        row = db.get_company(self.conn, company["id"])
        self.assertEqual(row["one_liner"], "Curated one-liner that must win.")

    def test_no_curated_file_unchanged(self):
        """Without a curated file, live mode keeps its legacy behaviour: the
        press fallback one-liner and an unknown, unsourced headcount."""
        company = self._company(website=None)
        evidence = [{"title": "Conduct raises", "url": "https://x.example",
                     "snippet": "Conduct, a London startup, raised a round."}]
        enrich.enrich_company(self.conn, company, evidence, fixtures=False)

        row = db.get_company(self.conn, company["id"])
        self.assertEqual(row["one_liner_source"],
                         "press summary (rewrite before featuring)")
        self.assertEqual(row["headcount_estimate"], "unknown")
        self.assertEqual(row["headcount_source"],
                         "not estimated; check the team page")

    def test_headcount_source_recorded_honestly(self):
        """The honest provenance string persists verbatim to the row, so the
        issue and public dataset show where the figure came from."""
        self._write_curated("15396489", {
            "headcount_estimate": "26-50",
            "headcount_source": "Clay (LinkedIn-derived), 2026-06-29",
        })
        company = self._company()
        enrich.enrich_company(self.conn, company, [], fixtures=False)

        row = db.get_company(self.conn, company["id"])
        self.assertEqual(row["headcount_source"],
                         "Clay (LinkedIn-derived), 2026-06-29")


class TestAtsOwnershipCorroboration(unittest.TestCase):
    """A guessed slug that any provider answers 200 for is not proof the
    board belongs to this company; without corroboration an unrelated
    company's postings would be published as a verified hiring signal
    (audit finding M4)."""

    def setUp(self):
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        self.addCleanup(self.conn.close)
        cid = db.upsert_company(self.conn, "Acme Analytics")
        self.company = db.get_company(self.conn, cid)
        # ats.fetch stub: greenhouse answers 200 for the guessed slug
        self.orig_fetch = enrich.ats.fetch
        enrich.ats.fetch = lambda provider, token, fixtures=False: (
            {"status": "verified",
             "jobs": [{"title": "Engineer", "location": "Remote",
                       "url": "https://boards.greenhouse.io/x/1"}]}
            if provider == "greenhouse"
            else {"status": "unverifiable", "jobs": []})
        self.addCleanup(setattr, enrich.ats, "fetch", self.orig_fetch)

    def test_uncorroborated_board_is_rejected(self):
        # the hosted page belongs to a different company entirely
        page = lambda url: "<title>Careers at Zenith Robotics</title>"
        provider, token, result = enrich._discover_ats(
            self.company, fixtures=False, page_fetch=page)
        self.assertIsNone(provider)
        self.assertIsNone(result)

    def test_corroborated_board_is_accepted(self):
        page = lambda url: "<h1>Acme Analytics is hiring in London</h1>"
        provider, token, result = enrich._discover_ats(
            self.company, fixtures=False, page_fetch=page)
        self.assertEqual(provider, "greenhouse")
        self.assertEqual(result["status"], "verified")

    def test_unreachable_hosted_page_is_rejected(self):
        provider, token, result = enrich._discover_ats(
            self.company, fixtures=False, page_fetch=lambda url: None)
        self.assertIsNone(provider)

    def test_fixture_mode_trusts_recorded_fixtures(self):
        provider, token, result = enrich._discover_ats(
            self.company, fixtures=True,
            page_fetch=lambda url: self.fail("no page fetch in fixtures"))
        self.assertEqual(provider, "greenhouse")


class TestJobExpiry(unittest.TestCase):
    """Postings age out honestly: every fetch stamps last_seen on what it
    saw, and publish exports only each company's latest-fetch postings, so
    a closed role disappears from the site without deleting its history."""

    def setUp(self):
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        self.addCleanup(self.conn.close)
        self.cid = db.upsert_company(self.conn, "Acme Analytics")

    def job(self, url):
        return {"title": "Engineer", "location": "London", "url": url}

    def test_second_fetch_stamps_survivors_only(self):
        enrich._record_jobs(self.conn, self.cid, "ashby",
                            [self.job("u1"), self.job("u2")],
                            seen_at="2026-07-01T10:00:00")
        enrich._record_jobs(self.conn, self.cid, "ashby",
                            [self.job("u1")],
                            seen_at="2026-07-03T10:00:00")
        rows = {r["url"]: r["last_seen"] for r in self.conn.execute(
            "SELECT url, last_seen FROM jobs")}
        self.assertEqual(rows["u1"], "2026-07-03T10:00:00")
        self.assertEqual(rows["u2"], "2026-07-01T10:00:00")
        current = self.conn.execute(
            "SELECT url FROM jobs WHERE last_seen = (SELECT MAX(last_seen) "
            "FROM jobs WHERE company_id = ?)", (self.cid,)).fetchall()
        self.assertEqual([r["url"] for r in current], ["u1"])

    def test_refresh_leaves_postings_on_fetch_error(self):
        enrich._record_jobs(self.conn, self.cid, "ashby", [self.job("u1")],
                            seen_at="2026-07-01T10:00:00")
        self.conn.execute(
            "UPDATE companies SET ats_status = 'verified', "
            "ats_provider = 'ashby', ats_token = 'acme' WHERE id = ?",
            (self.cid,))
        event, _ = __import__("radar.ingest", fromlist=["ingest"]).\
            find_or_create_event(self.conn, self.cid, "2026-06-20", "fixture")
        for status in ("sieved", "enriched", "featured"):
            db.advance_status(self.conn, event, status)
        orig = enrich.ats.fetch
        enrich.ats.fetch = lambda p, t, fixtures=False: {
            "status": "error", "jobs": []}
        self.addCleanup(setattr, enrich.ats, "fetch", orig)
        self.assertEqual(enrich.refresh_jobs(self.conn), 0)
        row = self.conn.execute("SELECT last_seen FROM jobs").fetchone()
        self.assertEqual(row["last_seen"], "2026-07-01T10:00:00")

    def test_init_db_migrates_an_old_jobs_table(self):
        import sqlite3
        old = sqlite3.connect(":memory:")
        old.row_factory = sqlite3.Row
        old.executescript(
            "CREATE TABLE jobs (id INTEGER PRIMARY KEY, company_id INTEGER "
            "NOT NULL, title TEXT NOT NULL, location TEXT, url TEXT, "
            "ats_provider TEXT, first_seen TEXT NOT NULL DEFAULT "
            "(datetime('now')), UNIQUE (company_id, url));"
            "INSERT INTO jobs (company_id, title, url, first_seen) "
            "VALUES (1, 'Engineer', 'u1', '2026-06-01T09:00:00');")
        db.init_db(old)
        row = old.execute("SELECT last_seen FROM jobs").fetchone()
        self.assertEqual(row["last_seen"], "2026-06-01T09:00:00")


if __name__ == "__main__":
    unittest.main()
