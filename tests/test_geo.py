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

    def test_london_counts_as_uk(self):
        self.assertTrue(geo.contains_uk("a Shoreditch startup"))


class TestUkWideGate(unittest.TestCase):
    def test_uk_cities_pass(self):
        for text in ("a Manchester fintech", "based in Edinburgh",
                     "Cardiff, Wales", "offices in Bristol",
                     "a Birmingham health startup"):
            self.assertTrue(geo.contains_uk(text), text)

    def test_home_nations_pass(self):
        for text in ("headquartered in Scotland", "a team in Wales",
                     "based in Northern Ireland"):
            self.assertTrue(geo.contains_uk(text), text)

    def test_uk_postcode_passes_without_a_named_place(self):
        self.assertTrue(geo.contains_uk("Registered office: Unit 4, M1 2AB"))
        self.assertEqual(geo.find_uk_marker("Unit 4, M1 2AB"), "uk postcode")

    def test_us_collisions_do_not_pass(self):
        for text in ("a lab in Cambridge, MA",
                     "Cambridge, Massachusetts based",
                     "headquartered in Manchester, NH",
                     "Birmingham, AL fintech"):
            self.assertFalse(geo.contains_uk(text), text)

    def test_common_words_are_not_uk_cities(self):
        # "reading" and "bath" are deliberately not city markers.
        self.assertFalse(geo.contains_uk("a platform for reading research"))
        self.assertFalse(geo.contains_uk("bath and skincare products"))

    def test_unrelated_us_location_does_not_pass(self):
        self.assertFalse(geo.contains_uk("somewhere in Ohio"))


class TestLocate(unittest.TestCase):
    def test_london_text_is_london(self):
        self.assertEqual(geo.locate("based in Hackney, London"),
                         ("london", "london"))

    def test_other_uk_text_is_uk(self):
        self.assertEqual(geo.locate("a Manchester fintech"),
                         ("uk", "manchester"))

    def test_london_takes_priority_over_uk(self):
        # Text naming both London and another UK place classifies as London.
        self.assertEqual(geo.classify_region(
            "a London team also hiring in Manchester"), "london")

    def test_non_uk_text_is_none(self):
        self.assertEqual(geo.locate("farms across Ukraine"), (None, None))

    def test_combine_evidence_text_joins_location_and_press(self):
        evidence = [{"title": "Acme raises", "snippet": "a Leeds startup"}]
        text = geo.combine_evidence_text("EC2A 3DU", evidence)
        self.assertIn("EC2A 3DU", text)
        self.assertIn("Leeds startup", text)


class TestForeignHQ(unittest.TestCase):
    """A non-UK HQ assertion in the press, used to veto a same-name UK office."""

    def test_place_based(self):
        self.assertTrue(geo.find_foreign_hq("Berlin-based manufacturing co"))
        self.assertTrue(geo.find_foreign_hq("a Stockholm-based water startup"))
        self.assertTrue(geo.find_foreign_hq("New York-based fintech"))

    def test_the_nationality_company(self):
        self.assertTrue(geo.find_foreign_hq(
            "Wayout, the Swedish developer of water tech"))
        self.assertTrue(geo.find_foreign_hq("the German company raised a round"))

    def test_based_in_foreign(self):
        self.assertTrue(geo.find_foreign_hq("headquartered in Amsterdam"))

    def test_uk_company_is_not_foreign(self):
        self.assertIsNone(geo.find_foreign_hq("London-based fintech"))
        self.assertIsNone(geo.find_foreign_hq("the British company raised"))
        self.assertIsNone(geo.find_foreign_hq("a London seed round"))

    def test_foreign_mention_is_not_an_hq(self):
        # a foreign co-founder or an expansion plan must not trip the veto
        self.assertIsNone(geo.find_foreign_hq(
            "founded by a Swedish engineer, based in London"))
        self.assertIsNone(geo.find_foreign_hq("expanding to Berlin next year"))

    def test_northern_ireland_is_not_ireland(self):
        # "ireland" in FOREIGN_PLACES must not fire inside Northern Ireland
        self.assertIsNone(geo.find_foreign_hq(
            "a Northern Ireland-based agritech"))
        self.assertIsNone(geo.find_foreign_hq(
            "the Northern Ireland based cyber startup"))
        self.assertEqual(geo.locate("a Northern Ireland-based agritech"),
                         ("uk", "northern ireland"))

    def test_republic_of_ireland_still_vetoes(self):
        self.assertTrue(geo.find_foreign_hq("a Dublin-based fintech"))
        self.assertTrue(geo.find_foreign_hq("an Ireland-based payments firm"))

    def test_commonwealth_place_based_vetoes(self):
        self.assertTrue(geo.find_foreign_hq(
            "a New South Wales-based agritech"))
        self.assertTrue(geo.find_foreign_hq(
            "a British Columbia-based mining startup"))


class TestCommonwealthCollisions(unittest.TestCase):
    """Bare nation tokens ("wales", "british", "britain") are whole words
    inside several Commonwealth place names; those phrases are masked so
    they can never pass the UK gate."""

    def test_new_south_wales_is_not_wales(self):
        self.assertEqual(geo.locate(
            "a New South Wales-based agritech, Australia"), (None, None))

    def test_british_columbia_is_not_british(self):
        self.assertEqual(geo.locate(
            "a British Columbia-based mining startup, Canada"), (None, None))

    def test_new_britain_is_not_britain(self):
        self.assertEqual(geo.locate(
            "a factory in New Britain, Connecticut"), (None, None))

    def test_london_kentucky_is_not_london(self):
        self.assertEqual(geo.locate("a plant in London, Kentucky"),
                         (None, None))

    def test_real_wales_still_passes(self):
        self.assertEqual(geo.locate("a Cardiff, Wales startup"),
                         ("uk", "wales"))
        self.assertEqual(geo.locate("a startup in rural Wales"),
                         ("uk", "wales"))

    def test_real_british_still_passes(self):
        self.assertEqual(geo.locate("the British startup raised"),
                         ("uk", "british"))


class TestConfigurableExclusions(unittest.TestCase):
    """sources.yaml extra_exclusion_phrases is the subtractive twin of the
    extra marker lists: a user-added marker's foreign collision can be
    masked without editing geo.py."""

    def setUp(self):
        import tempfile, shutil, os
        from pathlib import Path
        from radar import config
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "sources.yaml").write_text(
            "extra_uk_markers: [richmond]\n"
            "extra_exclusion_phrases: [\"richmond, virginia\"]\n")
        self.orig = config.SOURCES_PATH
        config.SOURCES_PATH = tmp / "sources.yaml"
        self.addCleanup(setattr, config, "SOURCES_PATH", self.orig)

    def test_extra_marker_with_masked_collision(self):
        self.assertEqual(geo.locate("offices in Richmond upon opening"),
                         ("uk", "richmond"))
        self.assertEqual(geo.locate("offices in Richmond, Virginia"),
                         (None, None))


if __name__ == "__main__":
    unittest.main()
