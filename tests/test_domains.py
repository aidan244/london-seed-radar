"""Pre-sieve domain resolution: candidate generation, the corroboration
guardrail (parked pages and same-name sites rejected), and writing a
verified website onto discovered companies. No network: fetch is injected."""

import unittest

from radar import db, domains


class TestCandidates(unittest.TestCase):
    def test_slug_variants_and_order(self):
        cands = domains.candidate_domains("Record OS")
        self.assertEqual(cands[0], "https://recordos.com")    # .com, nospace first
        self.assertIn("https://record-os.com", cands)         # hyphen variant
        self.assertEqual(domains.candidate_domains(""), [])


class TestCorroborates(unittest.TestCase):
    def test_accepts_named_page(self):
        self.assertTrue(domains.corroborates("<title>Flagright</title> AML", "Flagright"))
        self.assertTrue(domains.corroborates("<h1>Record OS</h1> tax", "Record OS"))

    def test_rejects_parked_page(self):
        self.assertFalse(domains.corroborates(
            "<html>This domain is for sale. Buy this domain.</html>", "Flagright"))

    def test_rejects_unrelated_page(self):
        self.assertFalse(domains.corroborates(
            "<p>A completely different company</p>", "Flagright"))
        self.assertFalse(domains.corroborates("", "Flagright"))

    def test_rejects_domain_marketplace_page(self):
        # A for-sale listing names the domain, so the name match alone must
        # not pass it (superlight.com sat on a Grails.com listing like this).
        page = ("Grails.com Strategic-Grade domain names for funded startups. "
                "SUPERLIGHT.COM is available for sale or other proposals.")
        self.assertFalse(domains.corroborates(page, "Superlight"))


PAGES = {
    "https://flagright.com": "<title>Flagright</title> AML compliance platform",
    "https://recordos.com": "<html>this domain is for sale</html>",  # parked
    "https://record-os.com": "<h1>Record OS</h1> UK tax returns",
}


class TestResolve(unittest.TestCase):
    def _fetch(self, url):
        return PAGES.get(url)

    def test_resolves_first_live_named_domain(self):
        self.assertEqual(domains.resolve_website("Flagright", self._fetch),
                         "https://flagright.com")

    def test_skips_parked_and_takes_hyphen_variant(self):
        self.assertEqual(domains.resolve_website("Record OS", self._fetch),
                         "https://record-os.com")

    def test_unresolved_returns_none(self):
        self.assertIsNone(domains.resolve_website("Ghostco", self._fetch))


class TestResolveDiscovered(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        self.addCleanup(self.conn.close)

    def _discovered(self, name, website=None):
        cid = db.upsert_company(self.conn, name, website=website)
        self.conn.execute(
            "INSERT INTO funding_events (company_id, event_date, source_mode) "
            "VALUES (?, '2026-06-20', 'live')", (cid,))
        return cid

    def test_sets_website_on_discovered_without_one(self):
        a = self._discovered("Flagright")
        b = self._discovered("Has Site", website="https://hassite.com")
        c = self._discovered("Ghostco")

        results = dict(domains.resolve_discovered(self.conn, self._fetch_pages))
        self.assertEqual(results["Flagright"], "https://flagright.com")
        self.assertIsNone(results["Ghostco"])
        self.assertNotIn("Has Site", results)   # already had a website, skipped

        rows = {r["name"]: r for r in self.conn.execute(
            "SELECT name, website, domain, website_status FROM companies")}
        self.assertEqual(rows["Flagright"]["website"], "https://flagright.com")
        self.assertEqual(rows["Flagright"]["domain"], "flagright.com")
        self.assertEqual(rows["Flagright"]["website_status"], "live")
        self.assertIsNone(rows["Ghostco"]["website"])

        # statuses are untouched: this step never advances the pipeline
        statuses = {r[0] for r in self.conn.execute(
            "SELECT DISTINCT status FROM funding_events")}
        self.assertEqual(statuses, {"discovered"})

    def _fetch_pages(self, url):
        return PAGES.get(url)


if __name__ == "__main__":
    unittest.main()
