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


class TestEntityResolution(unittest.TestCase):
    """A brand a lead pins by company_number must resolve only to that entity,
    never to a same-name company a naive search matched. The Humanoid crash:
    an unrelated active HUMANOID LTD (14835233) got created beside the funded
    SKL ROBOTICS LTD (15702488) and both then claimed thehumanoid.ai, aborting
    the sieve on UNIQUE(domain)."""

    WRONG = {"company_name": "HUMANOID LTD", "date_of_creation": "2021-01-01",
             "registered_office_address": {"address_line_1": "2 Foulden Terrace",
                                           "locality": "London",
                                           "postal_code": "N16 7UT"}}
    RIGHT = {"company_name": "SKL ROBOTICS LTD", "date_of_creation": "2024-05-03",
             "registered_office_address": {"address_line_1": "4-8 Ludgate Circus",
                                           "locality": "London",
                                           "postal_code": "EC4M 7LF"}}
    ITEM = {"company_name": "Humanoid", "stage": "series-a",
            "url": "https://thehumanoid.ai", "title": "Humanoid raises",
            "summary": "London robotics", "published_date": "2026-07-21",
            "source_name": "Forbes"}

    def _number_after_ingest(self, pinned):
        conn = db.connect(":memory:")
        db.init_db(conn)
        profiles = {"14835233": self.WRONG, "15702488": self.RIGHT}
        ingest.ingest_press(conn, [dict(self.ITEM)], profiles, "live", pinned)
        conn.commit()
        return [r["company_number"]
                for r in conn.execute("SELECT company_number FROM companies")]

    def test_pinned_brand_routes_name_only_item_to_pinned_entity(self):
        # With the brand pinned, the name-only press item attaches to the
        # funded entity, not the same-name company the register would match.
        self.assertEqual(self._number_after_ingest({"humanoid": "15702488"}),
                         ["15702488"])

    def test_without_pin_naive_match_takes_wrong_entity(self):
        # Documents the pre-fix behaviour the pin exists to prevent.
        self.assertEqual(self._number_after_ingest({}), ["14835233"])


class TestLiveProfileResolution(unittest.TestCase):
    class FakeClient:
        def __init__(self, hits, profiles):
            self._hits, self._profiles = hits, profiles
            self.searched, self.fetched = [], []

        def search_companies(self, q, items_per_page=5):
            self.searched.append(q)
            return self._hits.get(q, [])

        def get_profile(self, number):
            self.fetched.append(number)
            return self._profiles[number]

    def test_pinned_brand_is_not_name_searched(self):
        # A generic pinned brand is resolved via its number only; the name
        # search that would surface an unrelated same-name company is skipped.
        client = self.FakeClient(
            hits={"Humanoid": [{"title": "HUMANOID LTD",
                                "company_number": "14835233",
                                "company_status": "active"}]},
            profiles={"15702488": {"company_name": "SKL ROBOTICS LTD",
                                   "company_number": "15702488"},
                      "14835233": {"company_name": "HUMANOID LTD",
                                   "company_number": "14835233"}})
        profiles = ingest._live_profiles_for_items(
            client, [{"company_name": "Humanoid"}], watchlist=["15702488"],
            pinned_brands={"humanoid": "15702488"})
        self.assertIn("15702488", profiles)         # fetched via its number
        self.assertNotIn("14835233", profiles)      # wrong entity never entered
        self.assertNotIn("Humanoid", client.searched)  # search skipped entirely

    def test_dissolved_same_name_is_skipped(self):
        # A dissolved same-name shell is never resolved as a current raise
        # (the Kord and Polysense shells): only an active match is taken.
        client = self.FakeClient(
            hits={"Kord": [{"title": "KORD LTD", "company_number": "13666141",
                            "company_status": "dissolved"}]},
            profiles={})
        profiles = ingest._live_profiles_for_items(
            client, [{"company_name": "Kord"}], watchlist=[], pinned_brands={})
        self.assertEqual(profiles, {})              # dissolved hit not fetched
        self.assertEqual(client.fetched, [])


if __name__ == "__main__":
    unittest.main()
