"""Dedup at the DB level: company number, domain, normalized name; and
funding-event merging within the ingest window."""

import unittest

from radar import db
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


if __name__ == "__main__":
    unittest.main()
