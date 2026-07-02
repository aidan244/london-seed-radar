"""Companies House pure functions: SH01 filing extraction, registered
office text formatting, and fixture loading. Pinned offline; behaviour must
not depend on a live API call. CompaniesHouseClient itself is out of scope
here: it is never instantiated and its network methods (_get,
search_companies, get_profile, get_capital_filings) are never called. This
file only exercises the module's pure helpers, which are exactly what a
fixture-driven pipeline run needs to work offline.

Reminder of the honesty contract these functions serve (radar/ch.py
module docstring): an SH01 filing proves a raise happened and when, but
the capital_figure is a statement-of-capital figure, not the amount
raised. Callers are responsible for labelling it that way; this file
pins that extract_sh01_events returns exactly the fields callers need to
do so honestly, no more, no less.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from radar import ch, config


class TestExtractSh01Events(unittest.TestCase):
    def test_normal_sh01_item_extracts_date_transaction_capital_and_description(self):
        items = [{
            "category": "capital",
            "type": "SH01",
            "date": "2026-06-03",
            "description": "capital-allotment-shares",
            "description_values": {
                "date": "2026-06-03",
                "capital": [{"currency": "GBP", "figure": "2,151"}],
            },
            "transaction_id": "FIX16012001A",
        }]
        events = ch.extract_sh01_events(items)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["date"], "2026-06-03")
        self.assertEqual(event["transaction_id"], "FIX16012001A")
        self.assertEqual(event["capital_figure"], "2,151")
        self.assertEqual(event["description"], "capital-allotment-shares")

    def test_non_sh01_items_are_filtered_out(self):
        items = [
            {
                "category": "officers",
                "type": "AP01",
                "date": "2026-06-01",
                "description": "appoint-person-director-company",
                "transaction_id": "FIXAP01",
            },
            {
                "category": "capital",
                "type": "SH01",
                "date": "2026-06-03",
                "description": "capital-allotment-shares",
                "description_values": {
                    "date": "2026-06-03",
                    "capital": [{"currency": "GBP", "figure": "500"}],
                },
                "transaction_id": "FIXSH01",
            },
        ]
        events = ch.extract_sh01_events(items)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["transaction_id"], "FIXSH01")

    def test_missing_description_values_falls_back_to_item_date_with_none_figure(self):
        # description_values is entirely absent from the item (not just
        # empty); the function must fall back to the top-level date and
        # must not raise on the missing capital list.
        items = [{
            "category": "capital",
            "type": "SH01",
            "date": "2026-06-09",
            "description": "capital-allotment-shares",
            "transaction_id": "FIXNODV",
        }]
        events = ch.extract_sh01_events(items)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["date"], "2026-06-09")
        self.assertIsNone(event["capital_figure"])

    def test_empty_capital_list_gives_none_capital_figure(self):
        items = [{
            "category": "capital",
            "type": "SH01",
            "date": "2026-06-09",
            "description": "capital-allotment-shares",
            "description_values": {"date": "2026-06-09", "capital": []},
            "transaction_id": "FIXEMPTYCAP",
        }]
        events = ch.extract_sh01_events(items)
        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0]["capital_figure"])

    def test_returned_dict_has_exactly_the_four_keys(self):
        # Pins the statement-of-capital labelling contract: callers rely on
        # this exact shape (no "amount_raised" key, so no caller can be
        # tempted to treat capital_figure as the raise amount by accident).
        items = [{
            "category": "capital",
            "type": "SH01",
            "date": "2026-06-03",
            "description": "capital-allotment-shares",
            "description_values": {
                "date": "2026-06-03",
                "capital": [{"currency": "GBP", "figure": "2,151"}],
            },
            "transaction_id": "FIX16012001A",
        }]
        event = ch.extract_sh01_events(items)[0]
        self.assertEqual(set(event.keys()),
                         {"date", "transaction_id", "capital_figure",
                          "description"})

    def test_no_filing_items_returns_empty_list(self):
        self.assertEqual(ch.extract_sh01_events([]), [])


class TestRegisteredOfficeText(unittest.TestCase):
    def test_full_address_joins_all_five_parts_in_order(self):
        profile = {
            "registered_office_address": {
                "address_line_1": "1 Test Street",
                "address_line_2": "Floor 2",
                "locality": "Shoreditch",
                "region": "London",
                "postal_code": "EC2A 3DU",
            }
        }
        self.assertEqual(
            ch.registered_office_text(profile),
            "1 Test Street, Floor 2, Shoreditch, London, EC2A 3DU")

    def test_partial_address_skips_missing_keys_without_stray_commas(self):
        # Matches the shape of the recorded fixtures: address_line_2 and
        # region are absent, not empty strings.
        profile = {
            "registered_office_address": {
                "address_line_1": "12 Rivington Street",
                "locality": "Shoreditch, London",
                "postal_code": "EC2A 3DU",
            }
        }
        self.assertEqual(
            ch.registered_office_text(profile),
            "12 Rivington Street, Shoreditch, London, EC2A 3DU")

    def test_empty_registered_office_address_returns_empty_string(self):
        profile = {"registered_office_address": {}}
        self.assertEqual(ch.registered_office_text(profile), "")

    def test_profile_missing_registered_office_key_returns_empty_string(self):
        self.assertEqual(ch.registered_office_text({}), "")


class TestFixtureLoadersIsolated(unittest.TestCase):
    """Isolates config.FIXTURES_DIR to a temp directory so these tests do
    not depend on the contents of the real tests/fixtures/companies_house/
    directory (that is covered separately, against the real recorded
    fixtures, below)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.orig_fixtures_dir = config.FIXTURES_DIR
        config.FIXTURES_DIR = self.tmp
        self.addCleanup(setattr, config, "FIXTURES_DIR",
                        self.orig_fixtures_dir)
        self.ch_dir = self.tmp / "companies_house"

    def _write_profile(self, number, name):
        self.ch_dir.mkdir(parents=True, exist_ok=True)
        (self.ch_dir / ("%s_profile.json" % number)).write_text(json.dumps({
            "company_name": name,
            "company_number": number,
            "company_status": "active",
        }))

    def _write_filing_history(self, number, items):
        self.ch_dir.mkdir(parents=True, exist_ok=True)
        (self.ch_dir / ("%s_filing_history.json" % number)).write_text(
            json.dumps({"items": items, "total_count": len(items)}))

    def test_fixture_profiles_keyed_by_company_number(self):
        self._write_profile("90000001", "Alpha Test Ltd")
        self._write_profile("90000002", "Beta Test Ltd")
        profiles = ch.fixture_profiles()
        self.assertEqual(set(profiles.keys()), {"90000001", "90000002"})
        self.assertEqual(profiles["90000001"]["company_name"],
                         "Alpha Test Ltd")
        self.assertEqual(profiles["90000002"]["company_name"],
                         "Beta Test Ltd")

    def test_fixture_profiles_empty_when_directory_absent(self):
        # self.ch_dir is never created in this test.
        self.assertEqual(ch.fixture_profiles(), {})

    def test_fixture_capital_filings_returns_items_for_recorded_company(self):
        self._write_filing_history("90000001", [{
            "category": "capital", "type": "SH01", "date": "2026-06-03",
            "description": "capital-allotment-shares",
            "description_values": {
                "date": "2026-06-03",
                "capital": [{"currency": "GBP", "figure": "999"}],
            },
            "transaction_id": "FIX90000001A",
        }])
        items = ch.fixture_capital_filings("90000001")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["transaction_id"], "FIX90000001A")

    def test_fixture_capital_filings_returns_empty_list_when_file_absent(self):
        self.assertEqual(ch.fixture_capital_filings("90000099"), [])


class TestFixtureLoadersAgainstRecordedFixtures(unittest.TestCase):
    """Exercises the real, checked-in tests/fixtures/companies_house/
    fixtures (no network, no isolation needed: these files are static
    recorded data, the same fixtures radar.ch itself loads under
    --fixtures). Pins that the recorded set stays loadable and that the
    known no-capital-filings company (16012007) still round-trips to an
    empty list rather than a missing-file empty list, which exercises a
    different branch of fixture_capital_filings."""

    def test_real_fixture_profiles_load_and_key_by_company_number(self):
        profiles = ch.fixture_profiles()
        self.assertIn("16012001", profiles)
        self.assertEqual(profiles["16012001"]["company_name"],
                         "HEDGEROW LABS LTD")
        # every profile must be keyed under its own company_number
        for number, profile in profiles.items():
            self.assertEqual(profile["company_number"], number)

    def test_real_fixture_filing_history_for_known_company_has_sh01(self):
        items = ch.fixture_capital_filings("16012001")
        events = ch.extract_sh01_events(items)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["capital_figure"], "2,151")

    def test_real_fixture_filing_history_present_but_empty(self):
        # 16012007's recorded filing_history.json exists with items: [],
        # distinct from a company with no fixture file at all.
        items = ch.fixture_capital_filings("16012007")
        self.assertEqual(items, [])
        self.assertEqual(ch.extract_sh01_events(items), [])

    def test_real_fixture_filing_history_missing_file_returns_empty_list(self):
        items = ch.fixture_capital_filings("00000000")
        self.assertEqual(items, [])


if __name__ == "__main__":
    unittest.main()
