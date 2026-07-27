"""The four gates, run against crafted candidates and the recorded
enrichment fixtures (for the reality gate's website lookup)."""

import datetime
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from radar import config, db, sieve
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

    def test_recency_recovers_from_press_when_event_date_is_a_stale_filing(self):
        # event_date is a nominal SH01 before the window, but the round was
        # announced (press) inside it: the StirlingX and geoSurge recovery.
        ev = [{"kind": "filing", "title": "SH01",
               "snippet": "SH01 allotment", "published_date": "2026-05-01"},
              {"kind": "press", "title": "Testco raises a round",
               "snippet": "a London seed round", "published_date": "2026-06-05"}]
        ok, gates, reason = run(company(), event(date="2026-05-01"), ev)
        self.assertTrue(ok, reason)
        recency = [g for g in gates if g["gate"] == "recency"][0]
        self.assertTrue(recency["passed"])
        self.assertIn("most recent corroboration 2026-06-05", recency["detail"])

    def test_recency_drops_when_event_and_all_evidence_predate_window(self):
        # A recent-looking press date does not rescue a genuinely old round:
        # every corroboration must be inside the window.
        ev = [{"kind": "filing", "title": "SH01",
               "snippet": "SH01 allotment", "published_date": "2026-04-30"},
              {"kind": "press", "title": "Testco raises a round",
               "snippet": "a London seed round", "published_date": "2026-05-02"}]
        ok, _, reason = run(company(), event(date="2026-04-20"), ev)
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("recency:"))

    def test_recency_tolerates_missing_or_bad_evidence_dates(self):
        # Missing published_date, an empty one, and a non-ISO string must not
        # crash; recency falls back to the event_date.
        ev = [{"kind": "press", "title": "t", "snippet": "a London seed round"},
              {"kind": "press", "title": "t", "snippet": "x",
               "published_date": ""},
              {"kind": "press", "title": "t", "snippet": "y",
               "published_date": "not-a-date"}]
        ok, _, _ = run(company(), event(date="2026-06-03"), ev)
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


class TestResolveWebsiteLiveMode(unittest.TestCase):
    """radar.sieve.resolve_website's live-mode branch (fixtures=False), never
    covered before. Pins the precedence its docstring promises: 'a human-
    curated override wins over the row's website: the row can hold an
    auto-resolved guess (radar.domains), and a person who added an override
    is correcting it, so the override is authoritative.' Offline: liveness
    is driven by an injected stub for _check_website_live, never real
    requests, and sources.yaml itself is a temp file so nothing here touches
    the repo's real config."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.orig_sources_path = config.SOURCES_PATH
        self.addCleanup(setattr, config, "SOURCES_PATH", self.orig_sources_path)
        self.orig_check = sieve._check_website_live
        self.addCleanup(setattr, sieve, "_check_website_live", self.orig_check)
        self.calls = []

    def _write_sources(self, data):
        path = Path(self.tmp) / "sources.yaml"
        path.write_text(yaml.safe_dump(data))
        config.SOURCES_PATH = path

    def _stub_check(self, result):
        def fake(url):
            self.calls.append(url)
            return result
        sieve._check_website_live = fake

    def test_override_wins_over_row_website(self):
        # The row holds an auto-resolved guess; a human added an override to
        # correct it. The override must be the one checked and returned.
        self._write_sources(
            {"website_overrides": {"testco": "https://override.example.com"}})
        self._stub_check(True)
        c = company()
        c["website"] = "https://row-guess.example.com"

        url, reachable = sieve.resolve_website(c, fixtures=False)

        self.assertEqual(url, "https://override.example.com")
        self.assertTrue(reachable)
        self.assertEqual(self.calls, ["https://override.example.com"])

    def test_no_override_uses_row_website_liveness_from_checker(self):
        self._write_sources({})
        self._stub_check(True)
        c = company()
        c["website"] = "https://row.example.com"

        url, reachable = sieve.resolve_website(c, fixtures=False)

        self.assertEqual(url, "https://row.example.com")
        self.assertTrue(reachable)
        self.assertEqual(self.calls, ["https://row.example.com"])

    def test_no_override_row_website_unreachable_marks_dead(self):
        # Same row website as above, but the injected fetcher says it is
        # down: reachable must follow the checker, not just presence of a url.
        self._write_sources({})
        self._stub_check(False)
        c = company()
        c["website"] = "https://row.example.com"

        url, reachable = sieve.resolve_website(c, fixtures=False)

        self.assertEqual(url, "https://row.example.com")
        self.assertFalse(reachable)

    def test_no_override_no_website_fails_closed(self):
        # No override, no row website: nothing to check, so the checker is
        # never even called and the gate must fail closed.
        self._write_sources({})
        self._stub_check(True)
        c = company()
        c["website"] = None

        url, reachable = sieve.resolve_website(c, fixtures=False)

        self.assertIsNone(url)
        self.assertFalse(reachable)
        self.assertEqual(self.calls, [])

    def test_override_key_is_normalized_name_not_website(self):
        # Overrides are keyed by the company's normalized_name, not by a
        # website value; an unrelated key must not leak in.
        self._write_sources(
            {"website_overrides": {"someone-else": "https://wrong.example.com"}})
        self._stub_check(True)
        c = company()
        c["website"] = "https://row.example.com"

        url, reachable = sieve.resolve_website(c, fixtures=False)

        self.assertEqual(url, "https://row.example.com")
        self.assertTrue(reachable)


class TestSieveDomainCollision(unittest.TestCase):
    """Two companies resolving to one domain is a name/entity collision; the
    sieve drops the second with a reason rather than aborting the whole run on
    the UNIQUE(domain) constraint (the Humanoid duplicate crash)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.orig_sources = config.SOURCES_PATH
        self.addCleanup(setattr, config, "SOURCES_PATH", self.orig_sources)
        self.orig_check = sieve._check_website_live
        self.addCleanup(setattr, sieve, "_check_website_live", self.orig_check)
        sieve._check_website_live = lambda url: True
        path = Path(self.tmp) / "sources.yaml"
        path.write_text(yaml.safe_dump(
            {"lookback_days": 14,
             "website_overrides": {"newco": "https://collide.example"}}))
        config.SOURCES_PATH = path

    def test_domain_clash_drops_second_not_crashes(self):
        dbpath = str(Path(self.tmp) / "radar.db")
        conn = db.connect(dbpath)
        db.init_db(conn)
        # Company A already holds the domain the new company will resolve to.
        a = db.upsert_company(conn, "Existing Co", company_number="111",
                              location_text="London")
        conn.execute("UPDATE companies SET domain = ? WHERE id = ?",
                     ("collide.example", a))
        # Company B is a fresh discovered London seed whose override points at
        # the same domain.
        b = db.upsert_company(conn, "Newco", company_number="222",
                              location_text="London, EC1V 2NX")
        ev = conn.execute(
            "INSERT INTO funding_events (company_id, event_date, stage, status,"
            " source_mode) VALUES (?,?,?,?,?)",
            (b, "2026-07-20", "seed", "discovered", "live")).lastrowid
        db.add_evidence(conn, ev, "press", "UKTN", "https://x.example",
                        title="Newco raises", snippet="a London seed round",
                        published_date="2026-07-20")
        conn.commit()
        conn.close()

        rc = sieve.main(["--db", dbpath, "--as-of", "2026-07-26"])
        self.assertEqual(rc, 0)  # did not crash on UNIQUE(domain)

        conn = db.connect(dbpath)
        row = conn.execute("SELECT status, drop_reason FROM funding_events "
                           "WHERE id = ?", (ev,)).fetchone()
        self.assertEqual(row["status"], "dropped")
        self.assertIn("already claimed", row["drop_reason"])


if __name__ == "__main__":
    unittest.main()
