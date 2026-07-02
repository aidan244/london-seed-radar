"""Metrics honesty: one row per date enforced structurally, ISO date
validation, and amendment only as an explicit act. These numbers end up on
a CV; the table should make dishonesty-by-accident hard."""

import shutil
import tempfile
import unittest
from pathlib import Path

from radar import db, metrics


class TestMetricsLog(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db_path = str(self.tmp / "test.db")

    def log(self, *extra):
        return metrics.main(["--db", self.db_path, "log",
                             "--date", "2026-07-01",
                             "--subscribers", "42",
                             "--open-rate", "51.5", *extra])

    def rows(self):
        conn = db.connect(self.db_path)
        rows = conn.execute("SELECT * FROM metrics ORDER BY date").fetchall()
        conn.close()
        return rows

    def test_log_once(self):
        self.assertEqual(self.log(), 0)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["subscribers"], 42)

    def test_same_date_refuses_without_amend(self):
        self.assertEqual(self.log(), 0)
        self.assertEqual(self.log(), 2)
        self.assertEqual(len(self.rows()), 1)

    def test_amend_overwrites_in_place(self):
        self.assertEqual(self.log(), 0)
        self.assertEqual(metrics.main(
            ["--db", self.db_path, "log", "--date", "2026-07-01",
             "--subscribers", "45", "--open-rate", "52.0", "--amend"]), 0)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["subscribers"], 45)

    def test_non_iso_date_refused(self):
        self.assertEqual(metrics.main(
            ["--db", self.db_path, "log", "--date", "next tuesday",
             "--subscribers", "1"]), 2)
        self.assertEqual(len(self.rows()), 0)

    def test_unique_index_backstops_direct_inserts(self):
        # even bypassing cmd_log, the schema refuses duplicate dates
        import sqlite3
        conn = db.connect(self.db_path)
        db.init_db(conn)
        conn.execute("INSERT INTO metrics (date, subscribers) "
                     "VALUES ('2026-07-01', 1)")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO metrics (date, subscribers) "
                         "VALUES ('2026-07-01', 2)")
        conn.close()


if __name__ == "__main__":
    unittest.main()
