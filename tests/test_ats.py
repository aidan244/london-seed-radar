"""ATS board clients: the recorded-fixture honesty behaviour (a disabled
Ashby public API reports "unverifiable", never guessed), malformed-payload
resilience (one bad job entry degrades to "error" or is skipped, never a
crash), and title whitespace hygiene (untrimmed titles once reached the
public dataset). No network: live paths are exercised via a stubbed
requests.get."""

import unittest

from radar import ats


class FakeResponse:
    def __init__(self, status_code=200, payload=None, raises=None):
        self.status_code = status_code
        self._payload = payload
        self._raises = raises

    def json(self):
        if self._raises:
            raise self._raises
        return self._payload


class TestFixtureFetch(unittest.TestCase):
    def test_greenhouse_fixture_parses(self):
        result = ats.fetch("greenhouse", "foxglovedx", fixtures=True)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(len(result["jobs"]), 2)
        self.assertEqual(result["jobs"][0]["title"], "Lab Operations Associate")
        self.assertEqual(result["jobs"][0]["location"], "London")

    def test_ashby_disabled_api_is_unverifiable_never_guessed(self):
        # The recorded 404: org disabled the public posting API while the
        # hosted page still renders. CLAUDE.md: report unverifiable.
        result = ats.fetch("ashby", "tansymoney", fixtures=True)
        self.assertEqual(result["status"], "unverifiable")
        self.assertEqual(result["jobs"], [])

    def test_missing_fixture_is_unverifiable(self):
        result = ats.fetch("greenhouse", "no-such-org", fixtures=True)
        self.assertEqual(result["status"], "unverifiable")

    def test_unknown_provider_raises(self):
        with self.assertRaises(ValueError):
            ats.fetch("workable", "anyone", fixtures=True)


class TestMalformedPayloads(unittest.TestCase):
    """Public endpoints can 200 with unexpected shapes; every parser skips
    non-dict entries and _fetch degrades any parse failure to 'error'."""

    def test_null_job_entry_is_skipped(self):
        jobs = ats._parse_ashby({"jobs": [
            {"title": "Engineer", "location": "London",
             "jobUrl": "https://jobs.ashbyhq.com/x/1"},
            None,
        ]})
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["title"], "Engineer")

    def test_greenhouse_non_dict_entries_skipped(self):
        jobs = ats._parse_greenhouse({"jobs": ["oops", 3, None]})
        self.assertEqual(jobs, [])

    def test_lever_non_list_payload_raises_for_fetch_to_catch(self):
        with self.assertRaises(ValueError):
            ats._parse_lever({"unexpected": "dict"})

    def test_fetch_degrades_parse_crash_to_error(self):
        orig = ats.requests.get
        ats.requests.get = lambda url, timeout: FakeResponse(
            200, {"jobs": [None]})
        self.addCleanup(setattr, ats.requests, "get", orig)
        # ashby parser skips None entries, so use a payload whose shape
        # raises: jobs not iterable
        ats.requests.get = lambda url, timeout: FakeResponse(
            200, {"jobs": 42})
        result = ats.fetch_ashby("anyorg")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["jobs"], [])

    def test_fetch_404_is_unverifiable_live(self):
        orig = ats.requests.get
        ats.requests.get = lambda url, timeout: FakeResponse(404)
        self.addCleanup(setattr, ats.requests, "get", orig)
        self.assertEqual(ats.fetch_ashby("gone")["status"], "unverifiable")

    def test_fetch_500_is_error(self):
        orig = ats.requests.get
        ats.requests.get = lambda url, timeout: FakeResponse(500)
        self.addCleanup(setattr, ats.requests, "get", orig)
        self.assertEqual(ats.fetch_greenhouse("down")["status"], "error")


class TestTitleHygiene(unittest.TestCase):
    def test_titles_and_locations_are_stripped(self):
        # regression: untrimmed Ashby titles reached the public dataset
        jobs = ats._parse_ashby({"jobs": [
            {"title": "Platform Engineer  ", "location": " London ",
             "jobUrl": "https://jobs.ashbyhq.com/x/2"},
        ]})
        self.assertEqual(jobs[0]["title"], "Platform Engineer")
        self.assertEqual(jobs[0]["location"], "London")

    def test_missing_title_stays_none(self):
        jobs = ats._parse_greenhouse({"jobs": [{"absolute_url": "u"}]})
        self.assertIsNone(jobs[0]["title"])


if __name__ == "__main__":
    unittest.main()
