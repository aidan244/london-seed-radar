"""Word-boundary geography matching. The hard rule: markers match on
word boundaries only, never substrings. 'uk' must not match Ukraine,
'england' must not match New England."""

import unittest

from radar import geo


class TestLondonMarkers(unittest.TestCase):
    def test_plain_london(self):
        self.assertTrue(geo.contains_london("Based in London"))

    def test_neighbourhood_markers(self):
        self.assertTrue(geo.contains_london("12 Rivington Street, Shoreditch"))
        self.assertTrue(geo.contains_london("a Brixton-based health startup"))
        self.assertTrue(geo.contains_london("offices near King's Cross"))

    def test_case_insensitive(self):
        self.assertTrue(geo.contains_london("LONDON, EC2A"))

    def test_londonderry_is_not_london(self):
        self.assertFalse(geo.contains_london("headquartered in Londonderry"))

    def test_london_ontario_is_not_london(self):
        self.assertFalse(geo.contains_london("based in London, Ontario"))

    def test_new_england_is_not_england(self):
        self.assertFalse(geo.contains_london(
            "expanding its New England lab network"))

    def test_ukraine_has_no_london(self):
        self.assertFalse(geo.contains_london(
            "mapping soil health across Ukraine from Kyiv"))

    def test_returns_the_marker_found(self):
        self.assertEqual(geo.find_london_marker("Hackney Wick, London"),
                         "london")


class TestUkMarkers(unittest.TestCase):
    def test_uk_matches_on_word_boundary(self):
        self.assertTrue(geo.contains_uk("expanding across the UK"))

    def test_uk_does_not_match_ukraine(self):
        self.assertFalse(geo.contains_uk("farms across Ukraine"))

    def test_uk_does_not_match_inside_words(self):
        self.assertFalse(geo.contains_uk("the ukulele startup"))

    def test_england_matches_alone(self):
        self.assertTrue(geo.contains_uk("the north of England"))

    def test_england_does_not_match_new_england(self):
        self.assertFalse(geo.contains_uk("its New England lab network"))


if __name__ == "__main__":
    unittest.main()
