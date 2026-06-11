"""The forward-only status guard. discovered -> sieved -> enriched ->
featured -> published, dropped is terminal, nothing ever moves back."""

import unittest

from radar import db


def make_event(conn):
    company_id = db.upsert_company(conn, "Testco Ltd")
    cur = conn.execute(
        "INSERT INTO funding_events (company_id, event_date) VALUES (?, ?)",
        (company_id, "2026-06-01"))
    return cur.lastrowid


def status_of(conn, event_id):
    return conn.execute("SELECT status FROM funding_events WHERE id = ?",
                        (event_id,)).fetchone()["status"]


class TestStatusFlow(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        self.event = make_event(self.conn)

    def test_full_forward_walk(self):
        for status in ["sieved", "enriched", "featured", "published"]:
            db.advance_status(self.conn, self.event, status)
            self.assertEqual(status_of(self.conn, self.event), status)

    def test_backwards_raises(self):
        db.advance_status(self.conn, self.event, "enriched")
        with self.assertRaises(db.StatusFlowError):
            db.advance_status(self.conn, self.event, "sieved")
        self.assertEqual(status_of(self.conn, self.event), "enriched")

    def test_same_status_raises(self):
        db.advance_status(self.conn, self.event, "sieved")
        with self.assertRaises(db.StatusFlowError):
            db.advance_status(self.conn, self.event, "sieved")

    def test_forward_skip_is_allowed(self):
        db.advance_status(self.conn, self.event, "featured")
        self.assertEqual(status_of(self.conn, self.event), "featured")

    def test_published_is_terminal(self):
        db.advance_status(self.conn, self.event, "published")
        with self.assertRaises(db.StatusFlowError):
            db.advance_status(self.conn, self.event, "featured")
        with self.assertRaises(db.StatusFlowError):
            db.advance_status(self.conn, self.event, "dropped", "nope")

    def test_dropped_is_terminal(self):
        db.advance_status(self.conn, self.event, "dropped", "geography: test")
        for status in ["sieved", "enriched", "published"]:
            with self.assertRaises(db.StatusFlowError):
                db.advance_status(self.conn, self.event, status)
        self.assertEqual(status_of(self.conn, self.event), "dropped")

    def test_drop_requires_a_reason(self):
        with self.assertRaises(db.StatusFlowError):
            db.advance_status(self.conn, self.event, "dropped")

    def test_drop_records_the_reason(self):
        db.advance_status(self.conn, self.event, "dropped", "stage: series-b")
        row = self.conn.execute(
            "SELECT drop_reason FROM funding_events WHERE id = ?",
            (self.event,)).fetchone()
        self.assertEqual(row["drop_reason"], "stage: series-b")

    def test_unknown_status_raises(self):
        with self.assertRaises(db.StatusFlowError):
            db.advance_status(self.conn, self.event, "shipped")


if __name__ == "__main__":
    unittest.main()
