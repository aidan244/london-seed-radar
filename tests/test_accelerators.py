"""Accelerator mapping: anchor extraction filters nav/social and resolves
relative links, and the report writer produces a review file. No network
(fetch is injected) and no database is touched."""

import os
import shutil
import tempfile
import unittest

from radar import accelerators

HTML = """
<html><body>
<nav><a href="/about">About</a><a href="/portfolio">Portfolio</a></nav>
<section class="companies">
  <a href="https://acme.ai">Acme AI</a>
  <a href="/c/brixton-bio">Brixton Bio</a>
  <a href="mailto:hi@x.com">Email us</a>
  <a href="https://twitter.com/x">Twitter</a>
  <a href="/c/long">This is clearly a sentence and not a company name at all</a>
</section>
</body></html>
"""


class TestExtract(unittest.TestCase):
    def test_extract_filters_and_resolves(self):
        cands = dict((n.lower(), link) for n, link in
                     accelerators.extract_candidates(
                         HTML, "https://seedcamp.com/companies/"))
        self.assertIn("acme ai", cands)
        self.assertIn("brixton bio", cands)
        for junk in ("about", "portfolio", "twitter", "email us"):
            self.assertNotIn(junk, cands)
        self.assertNotIn("this is clearly a sentence and not a company name at all",
                         cands)
        self.assertEqual(cands["acme ai"], "https://acme.ai")
        self.assertEqual(cands["brixton bio"],
                         "https://seedcamp.com/c/brixton-bio")


class TestReport(unittest.TestCase):
    def test_write_report(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        mapping = accelerators.map_accelerators(
            [{"name": "Seedcamp", "url": "https://seedcamp.com/companies/"}],
            fetch=lambda url: HTML)
        rel = accelerators.write_report(tmp, mapping, today="2026-06-14")
        self.assertEqual(rel, "reports/accelerators/2026-06-14.md")
        text = open(os.path.join(tmp, rel)).read()
        self.assertIn("Acme AI", text)
        self.assertIn("Brixton Bio", text)
        self.assertIn("Review only", text)


class FakeCH:
    """Stand-in for ch.CompaniesHouseClient, the way TestReport injects fetch.
    search returns the recorded hits per query; profile returns the office."""
    def __init__(self, hits_by_query, profiles=None):
        self.hits_by_query = hits_by_query
        self.profiles = profiles or {}
        self.profile_calls = []

    def search_companies(self, query, items_per_page=5):
        return self.hits_by_query.get(query, [])

    def get_profile(self, number):
        self.profile_calls.append(number)
        return self.profiles[number]


class TestResolve(unittest.TestCase):
    def test_resolve_exact_name_match(self):
        client = FakeCH(
            {"Acme AI": [{"title": "ACME AI LTD", "company_number": "11112222",
                          "address_snippet": "1 High St, London"}]},
            {"11112222": {"registered_office_address": {
                "address_line_1": "1 High St", "locality": "London",
                "postal_code": "EC1A 1AA"}}})
        [row] = accelerators.resolve_to_numbers([("Acme AI", "https://acme.ai")],
                                                client)
        self.assertEqual(row["confidence"], "exact-name")
        self.assertEqual(row["company_number"], "11112222")
        self.assertEqual(row["register_name"], "ACME AI LTD")
        self.assertIn("London", row["office"])

    def test_resolve_ambiguous_collision(self):
        """Two register-name matches must not pick one: the TurnUp guard."""
        client = FakeCH(
            {"Acme AI": [
                {"title": "ACME AI LTD", "company_number": "11112222"},
                {"title": "Acme AI Limited", "company_number": "33334444"}]})
        [row] = accelerators.resolve_to_numbers([("Acme AI", "https://acme.ai")],
                                                client)
        self.assertEqual(row["confidence"], "ambiguous")
        self.assertIsNone(row["company_number"])

    def test_resolve_no_match(self):
        client = FakeCH(
            {"Acme AI": [{"title": "Totally Different Co Ltd",
                          "company_number": "55556666"}]})
        [row] = accelerators.resolve_to_numbers([("Acme AI", "https://acme.ai")],
                                                client)
        self.assertEqual(row["confidence"], "unresolved")
        self.assertIsNone(row["company_number"])

    def test_write_proposed_watchlist(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        resolved = [
            {"name": "Acme AI", "link": "https://acme.ai",
             "company_number": "11112222", "register_name": "ACME AI LTD",
             "office": "1 High St, London, EC1A 1AA", "confidence": "exact-name"},
            {"name": "Brixton Bio", "link": "https://brixtonbio.example",
             "company_number": None, "register_name": None, "office": None,
             "confidence": "ambiguous"},
            {"name": "Ghost Co", "link": "https://ghost.example",
             "company_number": None, "register_name": None, "office": None,
             "confidence": "unresolved"},
        ]
        rel = accelerators.write_proposed_watchlist(tmp, resolved,
                                                    today="2026-06-29")
        self.assertEqual(rel,
                         "reports/accelerators/proposed-watchlist-2026-06-29.md")
        text = open(os.path.join(tmp, rel)).read()
        self.assertIn("Confirm before adding (exact-name match)", text)
        self.assertIn("Ambiguous (pick by hand)", text)
        self.assertIn("Unresolved (no exact match)", text)
        # exact row shows number and office for the TurnUp confirmation
        self.assertIn("11112222", text)
        self.assertIn("1 High St, London", text)
        # the call writes no sources.yaml and no database
        self.assertFalse(os.path.exists(os.path.join(tmp, "sources.yaml")))
        self.assertFalse(os.path.exists(os.path.join(tmp, "radar.db")))


if __name__ == "__main__":
    unittest.main()
