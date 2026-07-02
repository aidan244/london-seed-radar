"""Dedup at the DB level: company number, domain, normalized name; and
funding-event merging within the ingest window."""

import unittest

from radar import db, ingest
from radar.ingest import find_or_create_event


class TestCompanyDedup(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)

    def count(self):
        return self.conn.execute(
            "SELECT COUNT(*) c FROM companies").fetchone()["c"]

    def test_same_company_number_is_one_row(self):
        a = db.upsert_company(self.conn, "Hedgerow Labs Ltd",
                              company_number="16012001")
        b = db.upsert_company(self.conn, "HEDGEROW LABS LTD",
                              company_number="16012001")
        self.assertEqual(a, b)
        self.assertEqual(self.count(), 1)

    def test_same_domain_is_one_row(self):
        a = db.upsert_company(self.conn, "Hedgerow", domain="hedgerow.example.com")
        b = db.upsert_company(self.conn, "Hedgerow Labs",
                              domain="hedgerow.example.com")
        self.assertEqual(a, b)
        self.assertEqual(self.count(), 1)

    def test_normalized_name_matches_legal_suffixes(self):
        a = db.upsert_company(self.conn, "Quillstone AI")
        b = db.upsert_company(self.conn, "QUILLSTONE AI LIMITED")
        self.assertEqual(a, b)
        self.assertEqual(self.count(), 1)

    def test_late_number_fills_in(self):
        a = db.upsert_company(self.conn, "Pellwharf")
        b = db.upsert_company(self.conn, "Pellwharf Ltd",
                              company_number="16012005")
        self.assertEqual(a, b)
        row = self.conn.execute("SELECT company_number FROM companies "
                                "WHERE id = ?", (a,)).fetchone()
        self.assertEqual(row["company_number"], "16012005")


class TestEventMerging(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        self.company = db.upsert_company(self.conn, "Testco Ltd")

    def test_nearby_dates_merge_into_one_event(self):
        a, new_a = find_or_create_event(self.conn, self.company,
                                        "2026-06-03", "fixture")
        b, new_b = find_or_create_event(self.conn, self.company,
                                        "2026-06-05", "fixture")
        self.assertTrue(new_a)
        self.assertFalse(new_b)
        self.assertEqual(a, b)

    def test_reingest_merges_into_dropped_events(self):
        # Regression: a re-run must not duplicate or resurrect a dropped
        # event; the same observation merges into it and it stays dropped.
        a, _ = find_or_create_event(self.conn, self.company,
                                    "2026-06-03", "fixture")
        db.advance_status(self.conn, a, "dropped", "recency: too old")
        b, new_b = find_or_create_event(self.conn, self.company,
                                        "2026-06-03", "fixture")
        self.assertEqual(a, b)
        self.assertFalse(new_b)
        status = self.conn.execute(
            "SELECT status FROM funding_events WHERE id = ?", (a,)
        ).fetchone()["status"]
        self.assertEqual(status, "dropped")

    def test_distant_dates_are_separate_events(self):
        a, _ = find_or_create_event(self.conn, self.company,
                                    "2026-01-05", "fixture")
        b, new_b = find_or_create_event(self.conn, self.company,
                                        "2026-06-05", "fixture")
        self.assertTrue(new_b)
        self.assertNotEqual(a, b)


class TestEvidenceDedup(unittest.TestCase):
    """Regression for the audit's M3: SQLite treats every NULL as distinct
    in a UNIQUE constraint, so url-less evidence (prose leads, link-less
    RSS entries) duplicated on every re-run. add_evidence stores '' so the
    UNIQUE actually fires."""

    def setUp(self):
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        company = db.upsert_company(self.conn, "Testco Ltd")
        self.event, _ = find_or_create_event(self.conn, company,
                                             "2026-06-03", "fixture")

    def count(self):
        return self.conn.execute(
            "SELECT COUNT(*) c FROM evidence WHERE funding_event_id = ?",
            (self.event,)).fetchone()["c"]

    def test_urlless_evidence_dedups_on_rerun(self):
        for _ in range(3):
            db.add_evidence(self.conn, self.event, "press", "scout (lead)",
                            None, title="Testco raises",
                            published_date="2026-06-03")
        self.assertEqual(self.count(), 1)

    def test_distinct_urls_still_both_kept(self):
        db.add_evidence(self.conn, self.event, "press", "UKTN",
                        "https://example.com/a")
        db.add_evidence(self.conn, self.event, "press", "UKTN",
                        "https://example.com/b")
        self.assertEqual(self.count(), 2)


class TestTerminalEventsAreImmutable(unittest.TestCase):
    """Regression for the audit's H3: a re-ingest must never rewrite the
    stage, amount, or date of a published (or dropped) event. The merge
    still matches the event and evidence may still accumulate, but the
    record itself is locked."""

    def setUp(self):
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        self.company = db.upsert_company(self.conn, "Testco Ltd")
        self.event, _ = find_or_create_event(self.conn, self.company,
                                             "2026-06-03", "fixture")
        ingest._update_event(self.conn, self.event, stage="seed",
                             amount_gbp=2_000_000, amount_source="press: UKTN")
        for status in ("sieved", "enriched", "featured", "published"):
            db.advance_status(self.conn, self.event, status)

    def row(self):
        return self.conn.execute(
            "SELECT * FROM funding_events WHERE id = ?", (self.event,)
        ).fetchone()

    def test_update_event_is_a_noop_on_published(self):
        ingest._update_event(self.conn, self.event, stage="series-a",
                             amount_gbp=45_000_000,
                             amount_source="press: other")
        row = self.row()
        self.assertEqual(row["stage"], "seed")
        self.assertEqual(row["amount_gbp"], 2_000_000)
        self.assertEqual(row["amount_source"], "press: UKTN")

    def test_update_event_is_a_noop_on_dropped(self):
        other, _ = find_or_create_event(self.conn, self.company,
                                        "2026-01-01", "fixture")
        db.advance_status(self.conn, other, "dropped", "recency: too old")
        ingest._update_event(self.conn, other, stage="seed",
                             amount_gbp=1_000_000)
        row = self.conn.execute(
            "SELECT * FROM funding_events WHERE id = ?", (other,)).fetchone()
        self.assertIsNone(row["stage"])
        self.assertIsNone(row["amount_gbp"])

    def test_filing_date_never_rewrites_a_published_event(self):
        profiles = {"16012099": {
            "company_name": "TESTCO LTD",
            "registered_office_address": {"locality": "London",
                                          "postal_code": "EC2A 4PS"},
            "date_of_creation": "2024-01-01",
        }}
        filings = {"16012099": [{
            "type": "SH01", "transaction_id": "TX1",
            "description_values": {"date": "2026-06-10"},
            "date": "2026-06-10", "description": "allotment",
        }]}
        import datetime
        ingest.ingest_filings(self.conn, profiles,
                              lambda n: filings[n],
                              datetime.date(2026, 7, 1), "fixture")
        row = self.row()
        self.assertEqual(row["event_date"], "2026-06-03")
        self.assertIsNone(row["filing_id"])
        self.assertEqual(row["status"], "published")

    def test_live_events_still_update(self):
        fresh, _ = find_or_create_event(self.conn, self.company,
                                        "2026-01-01", "fixture")
        ingest._update_event(self.conn, fresh, stage="pre-seed",
                             amount_gbp=500_000)
        row = self.conn.execute(
            "SELECT * FROM funding_events WHERE id = ?", (fresh,)).fetchone()
        self.assertEqual(row["stage"], "pre-seed")
        self.assertEqual(row["amount_gbp"], 500_000)


if __name__ == "__main__":
    unittest.main()
