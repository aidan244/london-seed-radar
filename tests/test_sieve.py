"""The four gates, run against crafted candidates and the recorded
enrichment fixtures (for the reality gate's website lookup)."""

import datetime
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from radar import config
from radar.sieve import evaluate_gates

AS_OF = datetime.date(2026, 6, 10)
WINDOW = 14


def company(location="12 Rivington Street, Shoreditch, London, EC2A 3DU",
            number="16012001"):
    return {"location_text": location, "company_number": number,
            "website": None, "normalized_name": "testco"}


def event(stage="seed", date="2026-06-03"):
    return {"stage": stage, "event_date": date}


def press(snippet, title="Testco raises a round"):
    return [{"kind": "press", "title": title, "snippet": snippet}]


def run(c, e, ev):
    return evaluate_gates(c, e, ev, AS_OF, WINDOW, fixtures=True)


class TestGates(unittest.TestCase):
    def test_all_four_gates_pass(self):
        ok, gates, reason = run(company(), event(), press("a London seed round"))
        self.assertTrue(ok)
        self.assertIsNone(reason)
        self.assertEqual([g["gate"] for g in gates],
                         ["geography", "stage", "recency", "reality"])
        self.assertTrue(all(g["passed"] for g in gates))

    def test_geography_drops_ukraine(self):
        ok, gates, reason = run(
            company(location=None), event(),
            press("mapping soil health across Ukraine from Kyiv"))
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("geography:"))

    def test_geography_drops_new_england(self):
        ok, _, reason = run(
            company(location=None), event(stage="series-a"),
            press("expanding its New England lab network"))
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("geography:"))

    def test_stage_unknown_drops(self):
        ok, _, reason = run(company(), event(stage=None),
                            press("an undisclosed London round"))
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("stage:"))

    def test_stage_series_b_drops(self):
        ok, _, reason = run(company(), event(stage="series-b"),
                            press("a London Series B"))
        self.assertFalse(ok)
        self.assertIn("series-b", reason)

    def test_recency_drops_old_events(self):
        ok, _, reason = run(company(), event(date="2026-04-20"),
                            press("a London seed round"))
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("recency:"))

    def test_recency_boundary_day_passes(self):
        ok, _, _ = run(company(), event(date="2026-05-27"),
                       press("a London seed round"))
        self.assertTrue(ok)

    def test_reality_drops_when_no_website(self):
        # 16012012 is the recorded stealth company with no live site.
        ok, _, reason = run(company(number="16012012"), event(),
                            press("a London seed round"))
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("reality:"))

    def test_gates_stop_at_first_failure(self):
        _, gates, _ = run(company(location=None), event(stage="series-b"),
                          press("somewhere in Ohio"))
        self.assertEqual(len(gates), 1)
        self.assertEqual(gates[0]["gate"], "geography")

    def test_geography_vetoes_foreign_hq_despite_uk_office(self):
        # London office attached, but the press calls it foreign: a same-name
        # match (the TurnUp lesson) must drop on geography.
        ok, _, reason = run(
            company(), event(stage="series-a"),
            press("the Swedish developer of water infrastructure",
                  title="Wayout raises a round"))
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("geography:"))
        self.assertIn("non-UK HQ", reason)

    def test_geography_vetoes_place_based_foreign(self):
        ok, _, reason = run(company(), event(stage="series-a"),
                            press("Berlin-based manufacturing intelligence"))
        self.assertFalse(ok)
        self.assertIn("non-UK HQ", reason)

    def test_geography_vetoes_non_gb_curated_hq_country(self):
        # press is silent on location; a Clay-verified hq_country drops it.
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        orig = config.ENRICHMENT_DIR
        config.ENRICHMENT_DIR = Path(tmp)
        self.addCleanup(setattr, config, "ENRICHMENT_DIR", orig)
        (Path(tmp) / "16012001.json").write_text(json.dumps({"hq_country": "US"}))
        ok, _, reason = run(company(), event(stage="series-a"),
                            press("Flagright funding lead"))
        self.assertFalse(ok)
        self.assertIn("HQ country US", reason)

    def test_genuine_london_company_still_passes(self):
        ok, _, _ = run(company(), event(),
                       press("a London seed round from a UK fintech"))
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
