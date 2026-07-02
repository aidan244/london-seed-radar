"""Pins radar/util.py's small shared helpers: slugify, parse_iso,
domain_of (including a current-behaviour bug with query strings),
resolve_as_of (including a current-behaviour ValueError propagation on a
malformed --as-of), and hr(). All pure functions, no I/O, no network."""

import argparse
import datetime
import unittest

from radar import util


class TestSlugify(unittest.TestCase):
    def test_lowercases_and_replaces_spaces(self):
        self.assertEqual(util.slugify("Capsa AI"), "capsa-ai")

    def test_strips_punctuation_and_collapses_runs(self):
        self.assertEqual(util.slugify("Foo, Bar & Co. Ltd."), "foo-bar-co-ltd")

    def test_strips_leading_and_trailing_dashes(self):
        self.assertEqual(util.slugify("  --Weird Name!!--  "), "weird-name")

    def test_empty_or_none_falls_back_to_company(self):
        self.assertEqual(util.slugify(""), "company")
        self.assertEqual(util.slugify(None), "company")

    def test_already_slug_shaped_is_unchanged(self):
        self.assertEqual(util.slugify("already-a-slug"), "already-a-slug")


class TestParseIso(unittest.TestCase):
    def test_valid_date_parses(self):
        self.assertEqual(util.parse_iso("2026-06-15"),
                         datetime.date(2026, 6, 15))

    def test_invalid_date_raises_value_error(self):
        with self.assertRaises(ValueError):
            util.parse_iso("15 June 2026")

    def test_empty_string_raises_value_error(self):
        with self.assertRaises(ValueError):
            util.parse_iso("")


class TestDomainOf(unittest.TestCase):
    def test_none_or_empty_returns_none(self):
        self.assertIsNone(util.domain_of(None))
        self.assertIsNone(util.domain_of(""))

    def test_https_url_with_path_returns_bare_domain(self):
        self.assertEqual(
            util.domain_of("https://example.com/careers/jobs"),
            "example.com")

    def test_www_prefix_is_stripped(self):
        self.assertEqual(
            util.domain_of("https://www.example.com/about"),
            "example.com")

    def test_bare_host_with_no_scheme_returns_none(self):
        # domain_of requires a "http(s)://" prefix to match at all; a bare
        # host string with no scheme never matches, so it returns None
        # rather than treating the whole string as the host. Current
        # (documented-here) behaviour, not asserted as ideal.
        self.assertIsNone(util.domain_of("example.com"))

    def test_query_string_with_no_path_is_included_in_domain(self):
        # BUG (pinning current behaviour, not fixing it here): the regex
        # r"https?://([^/]+)" only stops at a "/", so a URL that has a
        # query string but no path (e.g. "?ref=1" straight after the
        # host) leaks the query string into the returned "domain". See
        # radar/util.py:38-44.
        self.assertEqual(
            util.domain_of("https://example.com?ref=1"),
            "example.com?ref=1")


class TestResolveAsOf(unittest.TestCase):
    def test_valid_as_of_is_used(self):
        args = argparse.Namespace(as_of="2026-06-20")
        self.assertEqual(util.resolve_as_of(args), datetime.date(2026, 6, 20))

    def test_missing_as_of_attribute_falls_back_to_today(self):
        args = argparse.Namespace()
        self.assertEqual(util.resolve_as_of(args), datetime.date.today())

    def test_none_as_of_falls_back_to_today(self):
        args = argparse.Namespace(as_of=None)
        self.assertEqual(util.resolve_as_of(args), datetime.date.today())

    def test_malformed_as_of_propagates_value_error(self):
        # Current behaviour (pinned, not fixed here): resolve_as_of does
        # not catch parse_iso's ValueError, so a malformed --as-of value
        # crashes the caller with a raw ValueError instead of a clean CLI
        # error message. See radar/util.py:32-35.
        args = argparse.Namespace(as_of="not-a-date")
        with self.assertRaises(ValueError):
            util.resolve_as_of(args)


class TestHr(unittest.TestCase):
    def test_no_title_returns_bare_line(self):
        line = "=" * 64
        self.assertEqual(util.hr(), line)

    def test_empty_title_returns_bare_line(self):
        line = "=" * 64
        self.assertEqual(util.hr(""), line)

    def test_title_is_sandwiched_between_two_lines(self):
        line = "=" * 64
        self.assertEqual(util.hr("Weekly loop"),
                         "%s\nWeekly loop\n%s" % (line, line))


if __name__ == "__main__":
    unittest.main()
