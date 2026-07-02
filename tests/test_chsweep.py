"""The Companies House SH01 discovery sweep: window filtering, London-first
ordering, the honesty labels, and the no-database property. Offline: the
client is a fake; nothing touches the network or radar.db."""

import datetime
import unittest

from radar import chsweep


def _company(name, number, locality, created="2025-01-10"):
    return {"company_name": name, "company_number": number,
            "company_status": "active", "date_of_creation": created,
            "registered_office_address": {"address_line_1": "1 Test St",
                                          "locality": locality,
                                          "postal_code": "EC2A 4PS"}}


def _sh01(date, figure=None, tx="TX1"):
    return {"type": "SH01", "transaction_id": tx, "date": date,
            "description": "allotment",
            "description_values": ({"date": date, "capital":
                                    [{"figure": figure}]} if figure
                                   else {"date": date})}


class FakeClient:
    def __init__(self, pages, filings):
        self.pages = pages          # list of advanced-search pages
        self.filings = filings      # number -> filing items

    def advanced_search(self, size=100, start_index=0, **kw):
        idx = start_index // size
        return self.pages[idx] if idx < len(self.pages) else []

    def get_capital_filings(self, number):
        return self.filings.get(number, [])


class TestSweep(unittest.TestCase):
    AS_OF = datetime.date(2026, 7, 1)

    def test_window_filters_and_london_sorts_first(self):
        client = FakeClient(
            [[_company("MANCS DATA LTD", "1001", "Manchester"),
              _company("SOHO AI LTD", "1002", "London"),
              _company("OLD NEWS LTD", "1003", "London"),
              _company("QUIET LTD", "1004", "Leeds")]],
            {"1001": [_sh01("2026-06-20", "5000")],
             "1002": [_sh01("2026-06-25")],
             "1003": [_sh01("2026-01-05")],       # outside the window
             "1004": []},                          # no SH01 at all
        )
        candidates, scanned = chsweep.sweep(
            client, self.AS_OF, window_days=30, incorporated_from=None,
            sics=None, location=None, max_companies=10)
        self.assertEqual(scanned, 4)
        self.assertEqual([c["number"] for c in candidates], ["1002", "1001"])
        self.assertEqual(candidates[0]["region"], "london")
        self.assertEqual(candidates[1]["region"], "uk")

    def test_max_companies_caps_the_scan(self):
        client = FakeClient(
            [[_company("A LTD", "1", "London"),
              _company("B LTD", "2", "London"),
              _company("C LTD", "3", "London")]],
            {"1": [_sh01("2026-06-25")], "2": [_sh01("2026-06-25")],
             "3": [_sh01("2026-06-25")]},
        )
        candidates, scanned = chsweep.sweep(
            client, self.AS_OF, 30, None, None, None, max_companies=2)
        self.assertEqual(scanned, 2)
        self.assertEqual(len(candidates), 2)

    def test_one_bad_filing_history_does_not_abort(self):
        class FlakyClient(FakeClient):
            def get_capital_filings(self, number):
                if number == "1":
                    raise RuntimeError("boom")
                return super().get_capital_filings(number)
        client = FlakyClient(
            [[_company("A LTD", "1", "London"),
              _company("B LTD", "2", "London")]],
            {"2": [_sh01("2026-06-25")]},
        )
        candidates, scanned = chsweep.sweep(
            client, self.AS_OF, 30, None, None, None, max_companies=10)
        self.assertEqual([c["number"] for c in candidates], ["2"])

    def test_report_carries_the_honesty_labels(self):
        client = FakeClient(
            [[_company("SOHO AI LTD", "1002", "London")]],
            {"1002": [_sh01("2026-06-25", "12345")]},
        )
        candidates, scanned = chsweep.sweep(
            client, self.AS_OF, 30, None, None, None, 10)
        report = chsweep.render_report(candidates, scanned, self.AS_OF,
                                       30, 10)
        self.assertIn("NOT the amount raised", report)
        self.assertIn("company_number", report)   # the add-a-lead recipe
        self.assertIn("Soho Ai Ltd (1002)", report)
        self.assertNotIn("\u2014", report)   # no em dashes, ever

    def test_module_never_touches_the_database(self):
        import radar.chsweep as mod
        source = open(mod.__file__).read()
        self.assertNotIn("radar.db", source.replace("radar.db and", ""))
        self.assertNotIn("import db", source)
        self.assertNotIn("db.connect", source)


if __name__ == "__main__":
    unittest.main()
