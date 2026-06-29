"""Leads flow through the ordinary ingest path: load_leads gathers scout
and manual leads, and ingest_press turns them into discovered events that
the sieve will then gate. No network: leads come from a tmp reports dir and
a sources dict, and ingest_press runs against an in-memory database."""

import os
import shutil
import tempfile
import unittest

from radar import db, ingest, leads

SCOUT = (
    "```radar-leads (csv)\n"
    "name,stage,amount_gbp,date,url,source\n"
    "Brixton Bio,seed,1500000,2026-06-02,https://brixtonbio.example,UKTN\n"
    "```\n"
)


class TestIngestLeads(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        scout = os.path.join(self.tmp, "reports", "scout")
        os.makedirs(scout)
        with open(os.path.join(scout, "2026-06-13.md"), "w") as f:
            f.write(SCOUT)

    def test_leads_become_discovered_events(self):
        sources = {"leads": [
            {"name": "Acme AI", "stage": "seed", "url": "https://acme.ai",
             "date": "2026-06-10"}]}
        items = leads.load_leads(self.tmp, sources)
        self.assertEqual({i["company_name"] for i in items},
                         {"Brixton Bio", "Acme AI"})

        conn = db.connect(":memory:")
        db.init_db(conn)
        ingest.ingest_press(conn, items, {}, "fixture")
        conn.commit()

        discovered = conn.execute(
            "SELECT COUNT(*) c FROM funding_events WHERE status = 'discovered'"
        ).fetchone()["c"]
        self.assertEqual(discovered, 2)
        names = {r["name"] for r in conn.execute("SELECT name FROM companies")}
        self.assertEqual(names, {"Brixton Bio", "Acme AI"})
        # the seed stage carried through onto the event
        stages = {r["stage"] for r in conn.execute(
            "SELECT stage FROM funding_events")}
        self.assertEqual(stages, {"seed"})

    def test_explicit_company_number_resolves_brand_to_entity(self):
        """A lead's verified company_number attaches the right Companies
        House office to a brand whose registered name differs, instead of a
        naive name search that would miss or mis-resolve it."""
        items = leads.load_manual_leads({"leads": [
            {"name": "Conduct", "stage": "series-a", "date": "2026-06-17",
             "url": "https://conduct.ai", "company_number": "15396489"}]})
        self.assertEqual(items[0]["company_number"], "15396489")

        # The register name ("CONDUCT AI LTD") does not match the brand, so a
        # name search would fail; the explicit number must still resolve it.
        profiles = {"15396489": {
            "company_name": "CONDUCT AI LTD",
            "date_of_creation": "2024-01-08",
            "registered_office_address": {
                "address_line_1": "42 Berners Street",
                "locality": "London", "postal_code": "W1T 3ND"}}}

        conn = db.connect(":memory:")
        db.init_db(conn)
        ingest.ingest_press(conn, items, profiles, "live")
        conn.commit()

        row = conn.execute(
            "SELECT name, company_number, location_text FROM companies"
        ).fetchone()
        self.assertEqual(row["name"], "Conduct")           # brand kept for display
        self.assertEqual(row["company_number"], "15396489")  # right entity
        self.assertIn("London", row["location_text"])      # office attached


if __name__ == "__main__":
    unittest.main()
