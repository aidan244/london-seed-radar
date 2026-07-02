"""Stage detection and best-effort amount parsing."""

import unittest

from radar import stages


class TestDetectStage(unittest.TestCase):
    def test_seed(self):
        self.assertEqual(stages.detect_stage("closed a £2m seed round"), "seed")

    def test_pre_seed_beats_seed(self):
        self.assertEqual(stages.detect_stage("raised a pre-seed round"),
                         "pre-seed")
        self.assertEqual(stages.detect_stage("a preseed for the team"),
                         "pre-seed")

    def test_series_a(self):
        self.assertEqual(stages.detect_stage("an £8.5m Series A"), "series-a")

    def test_series_b_is_detected_but_out_of_scope(self):
        stage = stages.detect_stage("a £24m Series B")
        self.assertEqual(stage, "series-b")
        self.assertNotIn(stage, stages.IN_SCOPE_STAGES)

    def test_no_stage(self):
        self.assertIsNone(stages.detect_stage("hired a new CFO"))

    def test_seedcamp_is_not_a_seed_round(self):
        # Word boundary: "seedcamp" must not read as "seed".
        self.assertIsNone(stages.detect_stage("backed by Seedcamp earlier"))


class TestParseAmount(unittest.TestCase):
    def test_millions(self):
        self.assertEqual(stages.parse_amount_gbp("a £2.4m seed"), 2_400_000)

    def test_thousands(self):
        self.assertEqual(stages.parse_amount_gbp("raised £750k"), 750_000)

    def test_non_gbp_returns_none(self):
        self.assertIsNone(stages.parse_amount_gbp("raised $5m"))

    def test_comma_grouped_full_figures(self):
        # regression: £1,500,000 used to parse as 1500, a 1000x undercount
        self.assertEqual(
            stages.parse_amount_gbp("raised £1,500,000 in seed funding"),
            1_500_000)
        self.assertEqual(stages.parse_amount_gbp("a £850,000 pre-seed"),
                         850_000)
        self.assertEqual(
            stages.parse_amount_gbp("closed £12,000,000 series a"),
            12_000_000)

    def test_ambiguous_grouping_is_undisclosed(self):
        # digits continuing past the parsed figure mean the number was not
        # understood; undisclosed beats wrong
        self.assertIsNone(stages.parse_amount_gbp("raised £1,5m"))
        self.assertIsNone(stages.parse_amount_gbp("raised £1,5000"))

    def test_plain_and_decimal_still_work(self):
        self.assertEqual(stages.parse_amount_gbp("a £13.4m round"),
                         13_400_000)
        self.assertEqual(stages.parse_amount_gbp("£2bn fund"),
                         2_000_000_000)
        self.assertEqual(stages.parse_amount_gbp("about £1,500 spent"), 1_500)

    def test_format(self):
        self.assertEqual(stages.format_amount(2_400_000), "£2.4m")
        self.assertEqual(stages.format_amount(750_000), "£750k")
        self.assertEqual(stages.format_amount(None), "undisclosed")


if __name__ == "__main__":
    unittest.main()
