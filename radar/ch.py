"""Companies House client: live API plus recorded fixtures.

The funding-event trigger is an SH01 filing (allotment of shares) in the
filing history with category "capital". Known limit, stated honestly
everywhere it surfaces: SH01 proves a raise happened and when, but the
amount is usually inside an attached PDF, so amount-raised from filings
is best-effort and must be cross-checked against press.
"""

import json

import requests

from radar import config

BASE = "https://api.company-information.service.gov.uk"
TIMEOUT = 15


class CompaniesHouseClient:
    def __init__(self, api_key):
        if not api_key:
            raise ValueError("Companies House API key is required for live mode")
        self.session = requests.Session()
        self.session.auth = (api_key, "")

    def _get(self, path, **params):
        resp = self.session.get(BASE + path, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def search_companies(self, query, items_per_page=5):
        return self._get("/search/companies", q=query,
                         items_per_page=items_per_page).get("items", [])

    def get_profile(self, company_number):
        return self._get("/company/%s" % company_number)

    def get_capital_filings(self, company_number):
        data = self._get("/company/%s/filing-history" % company_number,
                         category="capital", items_per_page=50)
        return data.get("items", [])


def fixture_profiles():
    """All recorded company profiles, keyed by company number."""
    profiles = {}
    fixture_dir = config.FIXTURES_DIR / "companies_house"
    for path in sorted(fixture_dir.glob("*_profile.json")):
        profile = json.loads(path.read_text())
        profiles[profile["company_number"]] = profile
    return profiles


def fixture_capital_filings(company_number):
    path = (config.FIXTURES_DIR / "companies_house"
            / ("%s_filing_history.json" % company_number))
    if not path.exists():
        return []
    return json.loads(path.read_text()).get("items", [])


def extract_sh01_events(filing_items):
    """Pull SH01 allotment filings out of a capital filing history."""
    events = []
    for item in filing_items:
        if item.get("type") != "SH01":
            continue
        values = item.get("description_values", {})
        capital = values.get("capital") or []
        figure = capital[0].get("figure") if capital else None
        events.append({
            "date": values.get("date") or item.get("date"),
            "transaction_id": item.get("transaction_id"),
            # Statement-of-capital figure, NOT the amount raised.
            "capital_figure": figure,
            "description": item.get("description"),
        })
    return events


def registered_office_text(profile):
    office = profile.get("registered_office_address", {})
    parts = [office.get(k) for k in
             ("address_line_1", "address_line_2", "locality", "region",
              "postal_code")]
    return ", ".join(p for p in parts if p)
