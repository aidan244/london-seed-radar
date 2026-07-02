"""Issue assembly: the re-run guard (a second draft for the same date must
not strand the previously featured batch), the shortfall note, and the
forward-only wiring. File output is isolated to a temp dir by pointing
config.ISSUES_DIR at it; the DB is a temp file.

Also pins: the never-pad shortfall note actually appears in the rendered
draft when fewer companies qualify than companies_per_issue; gather_featured
sorts every London entry ahead of every other-UK entry regardless of score,
and _mark_section_heads flags the region transition; and score()'s actual
weighting (filing outranks press, a live job board adds a flat point
regardless of how many roles it lists). The region-ordering and score()
tests call db.connect(':memory:') directly and never go through the CLI, so
they skip the config.ISSUES_DIR/config.ROOT isolation those tests do not
need."""

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


def _make_enriched_custom(conn, name, event_date, number, location_text,
                          evidence_kinds=("press",), job_titles=()):
    """Like _make_enriched but with a controllable location, evidence
    kinds, and job list, for pinning gather_featured's region ordering and
    the score() contract. Evidence title/snippet deliberately never say
    "London", so a non-London fixture cannot pass the geography gate
    through the evidence text instead of its location_text."""
    company_id = db.upsert_company(
        conn, name, company_number=number,
        location_text=location_text,
        website="https://example.com/%s" % number,
        website_status="live", one_liner="Builds useful things for tests.",
        one_liner_source="test", headcount_estimate="1-10",
        headcount_source="test", ats_provider="greenhouse", ats_status="none")
    event, _ = __import__("radar.ingest", fromlist=["ingest"]).\
        find_or_create_event(conn, company_id, event_date, "fixture")
    conn.execute("UPDATE funding_events SET stage = 'seed', "
                 "amount_gbp = 1000000 WHERE id = ?", (event,))
    if "filing" in evidence_kinds:
        db.add_evidence(conn, event, "filing", "Companies House",
                        "https://find-and-update.company-information."
                        "service.gov.uk/company/%s" % number,
                        title="%s statement of capital" % name,
                        snippet="%s filed a confirmation of a new share "
                                "allotment." % name,
                        published_date=event_date)
    if "press" in evidence_kinds:
        db.add_evidence(conn, event, "press", "UKTN",
                        "https://example.com/press/%s" % number,
                        title="%s raises a seed round" % name,
                        snippet="%s raised a seed round, the company said."
                                % name,
                        published_date=event_date)
    for i, title in enumerate(job_titles):
        conn.execute(
            "INSERT INTO jobs (company_id, title, location, url, "
            "ats_provider) VALUES (?, ?, ?, ?, ?)",
            (company_id, title, location_text,
             "https://example.com/jobs/%s/%d" % (number, i), "greenhouse"))
    for status in ("sieved", "enriched"):
        db.advance_status(conn, event, status)
    return event


class TestIssueNeverPadsShortfall(unittest.TestCase):
    """CLAUDE.md 'Issue composition': if fewer companies qualify than
    companies_per_issue, the issue features the real ones and says so;
    it must never be padded or stretched to hit the target."""

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
        self.target = config.companies_per_issue()
        # The fixture assumes the configured target is above 2; if
        # sources.yaml ever drops companies_per_issue to 2 or below this
        # assumption needs revisiting, so fail loudly rather than pass
        # for the wrong reason.
        self.assertGreater(self.target, 2,
                           "fixture needs companies_per_issue > 2 to stay "
                           "a genuine shortfall")
        _make_enriched(conn, "Shortco", "2026-06-20", "16020001")
        _make_enriched(conn, "Fewco", "2026-06-21", "16020002")
        conn.commit()
        conn.close()

    def test_shortfall_features_all_and_exits_zero_with_honest_note(self):
        result = issue.main(["--db", str(self.db_path),
                             "--as-of", "2026-06-29"])
        self.assertEqual(result, 0)

        draft = config.ISSUES_DIR / "2026-06-29" / "draft-issue.md"
        text = draft.read_text()
        self.assertIn("Shortco", text)
        self.assertIn("Fewco", text)
        # Exact note text from radar/issue.py _issue_header: pinned here so
        # a change to the wording is a deliberate, visible edit.
        expected_note = ("[NOTE: only 2 companies qualified this fortnight "
                         "against a target of %d; say so plainly in the "
                         "intro, never pad.]" % self.target)
        self.assertIn(expected_note, text)

        conn = db.connect(self.db_path)
        featured = conn.execute(
            "SELECT COUNT(*) c FROM funding_events WHERE status = 'featured'"
        ).fetchone()["c"]
        conn.close()
        self.assertEqual(featured, 2)


class TestGatherFeaturedRegionOrdering(unittest.TestCase):
    """gather_featured always sorts every London entry ahead of every
    other-UK entry, even when the other-UK company is more corroborated
    and has live job postings (CLAUDE.md gate 1: 'issues lead with London
    and group the rest of the UK after it'). No CLI involved, so this uses
    an in-memory DB rather than the temp-dir/config-swap isolation the
    file-writing tests above need."""

    def setUp(self):
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        self.addCleanup(self.conn.close)
        # London: press-only evidence, no jobs -> low score, older date.
        _make_enriched_custom(
            self.conn, "Loco", "2026-06-10", "17010001",
            "1 Shoreditch High Street, London, E1 6JE",
            evidence_kinds=("press",), job_titles=())
        # Manchester: filing + press, two live roles -> higher score and a
        # more recent date. Should still sort after London.
        _make_enriched_custom(
            self.conn, "Mancco", "2026-06-20", "17010002",
            "1 Deansgate, Manchester, M3 2FW",
            evidence_kinds=("filing", "press"),
            job_titles=("Engineer", "Designer"))
        self.conn.commit()

    def test_manchester_scores_higher_but_london_sorts_first(self):
        featured = issue.gather_featured(self.conn, limit=2)
        self.assertEqual(len(featured), 2)
        names = [e["company"]["name"] for e in featured]
        regions = [e["region"] for e in featured]
        self.assertEqual(names, ["Loco", "Mancco"])
        self.assertEqual(regions, ["london", "uk"])
        # Pin the premise: Manchester really is the higher-scored entry,
        # so London sorting first is the region sort overriding score,
        # not a coincidence of the score/date sort alone.
        london_entry, manchester_entry = featured
        self.assertLess(london_entry["score"], manchester_entry["score"])

    def test_mark_section_heads_flags_the_region_transition(self):
        featured = issue.gather_featured(self.conn, limit=2)
        self.assertEqual(featured[0]["section_heading"], "London")
        self.assertEqual(featured[1]["section_heading"],
                         "Across the rest of the UK")

    def test_single_region_issue_gets_no_section_headings(self):
        # _mark_section_heads only inserts headings when the issue mixes
        # London and other-UK entries; a London-only issue should not
        # sprout a redundant "London" heading on every card.
        featured = issue.gather_featured(self.conn, limit=1)
        self.assertEqual(len(featured), 1)
        self.assertIsNone(featured[0]["section_heading"])


class TestScore(unittest.TestCase):
    """Pins score()'s actual contract (radar/issue.py): a filing is worth
    2, press is worth 1, and any live job count is worth a flat 1 no
    matter how many roles there are, so corroboration always outweighs
    the hiring signal."""

    def test_filing_and_press_corroborated_beats_press_only(self):
        corroborated = issue.score(None, {"filing", "press"}, 0)
        press_only = issue.score(None, {"press"}, 0)
        self.assertEqual(corroborated, 3)
        self.assertEqual(press_only, 1)
        self.assertGreater(corroborated, press_only)

    def test_corroboration_outranks_press_only_plus_jobs(self):
        # A filing+press event with no jobs still outscores a press-only
        # event that has a long jobs list: corroboration is weighted above
        # the hiring signal.
        corroborated_no_jobs = issue.score(None, {"filing", "press"}, 0)
        press_only_with_jobs = issue.score(None, {"press"}, 12)
        self.assertGreater(corroborated_no_jobs, press_only_with_jobs)

    def test_jobs_presence_adds_a_flat_point_not_scaled_by_count(self):
        no_jobs = issue.score(None, {"press"}, 0)
        one_job = issue.score(None, {"press"}, 1)
        many_jobs = issue.score(None, {"press"}, 250)
        self.assertEqual(one_job, no_jobs + 1)
        self.assertEqual(many_jobs, one_job)

    def test_evidence_kinds_only_needs_membership_testing(self):
        # gather_featured passes a set of evidence kinds; a plain list
        # scores identically because score() only ever tests "in".
        self.assertEqual(issue.score(None, ["filing"], 0),
                         issue.score(None, {"filing"}, 0))

    def test_no_evidence_and_no_jobs_scores_zero(self):
        self.assertEqual(issue.score(None, set(), 0), 0)
        self.assertEqual(issue.score(None, [], None), 0)


if __name__ == "__main__":
    unittest.main()
