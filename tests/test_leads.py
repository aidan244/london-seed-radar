"""Lead parsing: the machine-readable block wins when present, the prose
fallback reads the existing report format, non-GBP amounts become None
(never guessed), manual leads load from a sources dict, and leads dedup by
normalized company name keeping the most recent date."""

import os
import shutil
import tempfile
import unittest

from radar import leads

WITH_BLOCK = (
    "# Scout report\n\n"
    "### 1. RevEng.AI\n- **Detected stage:** Series A (prose, ignored)\n\n"
    "```radar-leads (csv)\n"
    "name,stage,amount_gbp,date,url,source\n"
    "RevEng.AI,series-a,,2026-05-27,https://reveng.ai,SecurityWeek\n"
    "Brixton Bio,seed,1500000,2026-06-02,https://brixtonbio.example,UKTN\n"
    "```\n"
)

PROSE_ONLY = (
    "## Shortlist\n\n"
    "### 1. RevEng.AI\n"
    "- **Detected stage:** Series A\n"
    "- **Parsed amount (GBP):** non-GBP press figure ($15M); no conversion\n"
    "- **Published date:** 2026-05-27\n"
    "- **URL:** https://reveng.ai\n"
    "- **Source:** SecurityWeek, The SaaS News\n\n"
    "### 2. Brixton Bio\n"
    "- **Detected stage:** Seed\n"
    "- **Parsed amount (GBP):** £1.5m\n"
    "- **Published date:** 2026-06-02\n"
    "- **Source:** https://uktech.news/brixton\n"
)


class TestParseScoutReport(unittest.TestCase):
    def test_machine_block_wins(self):
        items = {i["company_name"]: i for i in leads.parse_scout_report(WITH_BLOCK)}
        self.assertEqual(set(items), {"RevEng.AI", "Brixton Bio"})
        self.assertEqual(items["RevEng.AI"]["stage"], "series-a")
        self.assertIsNone(items["RevEng.AI"]["amount_gbp"])     # blank cell
        self.assertEqual(items["Brixton Bio"]["stage"], "seed")
        self.assertEqual(items["Brixton Bio"]["amount_gbp"], 1500000)
        self.assertEqual(items["Brixton Bio"]["published_date"], "2026-06-02")

    def test_prose_fallback(self):
        items = {i["company_name"]: i for i in leads.parse_scout_report(PROSE_ONLY)}
        self.assertEqual(set(items), {"RevEng.AI", "Brixton Bio"})
        # non-GBP figure must not be guessed into a number
        self.assertIsNone(items["RevEng.AI"]["amount_gbp"])
        self.assertEqual(items["RevEng.AI"]["stage"], "series-a")
        self.assertEqual(items["RevEng.AI"]["url"], "https://reveng.ai")
        # url pulled from the Source line when there is no URL field
        self.assertEqual(items["Brixton Bio"]["url"], "https://uktech.news/brixton")
        self.assertEqual(items["Brixton Bio"]["amount_gbp"], 1500000)


class TestDateNormalisation(unittest.TestCase):
    """Predraft prose carries human dates ('17 June 2026') and qualified
    prose ('approx. 10 June 2026 (featured in the roundup)'). These must
    become ISO or the lead is dropped; an unparseable date never reaches
    ingest, where it crashed find_or_create_event's parse_iso."""

    def test_iso_passthrough(self):
        self.assertEqual(leads._iso_date("2026-06-17"), "2026-06-17")

    def test_human_spellings(self):
        self.assertEqual(leads._iso_date("17 June 2026"), "2026-06-17")
        self.assertEqual(leads._iso_date("9 June 2026"), "2026-06-09")
        self.assertEqual(leads._iso_date("June 17, 2026"), "2026-06-17")

    def test_date_embedded_in_prose(self):
        self.assertEqual(
            leads._iso_date("approx. 10 June 2026 (featured in roundup)"),
            "2026-06-10")

    def test_unparseable_drops_to_none(self):
        self.assertIsNone(leads._iso_date("sometime soon"))
        self.assertIsNone(leads._iso_date(""))
        self.assertIsNone(leads._iso_date(None))

    def test_prose_human_date_makes_dated_item(self):
        report = ("## Shortlist\n\n"
                  "### 1. Conduct\n"
                  "- **Stage:** Series A\n"
                  "- **Date:** 17 June 2026\n"
                  "- **Source:** https://eu-startups.com/conduct\n")
        item = leads.parse_scout_report(report)[0]
        self.assertEqual(item["published_date"], "2026-06-17")


class TestCompanyNumber(unittest.TestCase):
    """A manual lead can carry a human-verified Companies House number for
    the exact entity, and the dedup never drops it."""

    def test_manual_lead_carries_number(self):
        items = leads.load_manual_leads({"leads": [
            {"name": "Conduct", "stage": "series-a", "date": "2026-06-17",
             "url": "https://conduct.ai", "company_number": "15396489"}]})
        self.assertEqual(items[0]["company_number"], "15396489")

    def test_lead_without_number_is_none(self):
        items = leads.load_manual_leads({"leads": [
            {"name": "Acme AI", "stage": "seed", "date": "2026-06-10",
             "url": "https://acme.ai"}]})
        self.assertIsNone(items[0]["company_number"])

    def test_dedup_preserves_number_when_dateless_dup_wins(self):
        # Same company: a manual lead with the verified number but an equal
        # date, and a scout duplicate. The number must survive the merge.
        items = [
            {"company_name": "Conduct", "published_date": "2026-06-17",
             "company_number": "15396489"},
            {"company_name": "conduct", "published_date": "2026-06-20",
             "company_number": None},
        ]
        out = leads._dedup(items)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["published_date"], "2026-06-20")  # recent wins
        self.assertEqual(out[0]["company_number"], "15396489")    # number kept


class TestManualAndCombine(unittest.TestCase):
    def test_manual_leads(self):
        sources = {"leads": [
            {"name": "Acme AI", "stage": "seed", "url": "https://acme.ai",
             "date": "2026-06-10"},
            {"name": "", "stage": "seed"},                 # no name: skipped
        ]}
        items = leads.load_manual_leads(sources)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["company_name"], "Acme AI")
        self.assertIn("manual lead", items[0]["source_name"])

    def test_dedup_keeps_most_recent(self):
        items = leads._dedup([
            {"company_name": "Acme AI", "published_date": "2026-06-01"},
            {"company_name": "acme ai", "published_date": "2026-06-09"},
        ])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["published_date"], "2026-06-09")

    def test_load_scout_leads_from_disk(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        scout = os.path.join(tmp, "reports", "scout")
        os.makedirs(scout)
        with open(os.path.join(scout, "2026-06-13.md"), "w") as f:
            f.write(WITH_BLOCK)
        names = {i["company_name"] for i in leads.load_scout_leads(tmp)}
        self.assertEqual(names, {"RevEng.AI", "Brixton Bio"})

    def test_one_unreadable_report_does_not_abort_the_load(self):
        # regression: a single badly-encoded cloud-written file used to
        # raise UnicodeDecodeError out of ingest, dropping every lead
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        scout = os.path.join(tmp, "reports", "scout")
        os.makedirs(scout)
        with open(os.path.join(scout, "2026-06-13.md"), "w") as f:
            f.write(WITH_BLOCK)
        with open(os.path.join(scout, "2026-06-20.md"), "wb") as f:
            f.write(b"\xff\xfe invalid utf-8 \x9c\x81")
        names = {i["company_name"] for i in leads.load_scout_leads(tmp)}
        self.assertEqual(names, {"RevEng.AI", "Brixton Bio"})


if __name__ == "__main__":
    unittest.main()
