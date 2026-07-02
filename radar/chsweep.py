"""Discovery sweep straight off the Companies House register: young
companies whose filing history shows a recent SH01 allotment, no press
coverage needed. This is the primary-discovery widener for raises the
feeds and scouts miss.

Review-only, like radar.accelerators: it never touches the database and
never auto-adds anything. It prints (or, with --write, saves to
reports/chsweep/<date>.md) a candidate list for a human to verify:
confirm the entity is really the company you think, find a press source
or the company site, then add it to sources.yaml leads with the verified
company_number. The four gates still judge it like any other candidate.

Bounded on purpose: the advanced search matches tens of thousands of
young companies and each candidate costs one filing-history call against
the API's rate budget (600 requests per 5 minutes), so a run scans at
most --max-companies (default 150, hard cap 400) and says exactly how
far it got. Run it repeatedly over time rather than raising the cap.

  python -m radar.chsweep [--window 30] [--max-companies 150]
      [--incorporated-from YYYY-MM-DD] [--location london]
      [--sic 62012 --sic 62020 ...] [--write]

An SH01 proves a raise happened and when; the statement-of-capital
figure is NOT the amount raised. Every line of the output says so.
"""

import argparse
import datetime
import sys

from radar import ch, config, geo, util

# Default SIC codes: the software/data/tech set where UK seed activity
# concentrates. Override per run with --sic.
DEFAULT_SICS = [
    "62012",   # business and domestic software development
    "62020",   # IT consultancy
    "62090",   # other IT service activities
    "63110",   # data processing and hosting
    "63120",   # web portals
    "72190",   # other natural-sciences R&D
    "72110",   # biotechnology R&D
]
PAGE_SIZE = 100
HARD_CAP = 400
CH_COMPANY_URL = ("https://find-and-update.company-information.service"
                  ".gov.uk/company/%s")


def sweep(client, as_of, window_days, incorporated_from, sics, location,
          max_companies, progress=None):
    """Scan up to max_companies young companies for SH01 allotments inside
    the window. Returns (candidates, scanned): candidates is a list of
    {name, number, incorporated, office, region, sh01_date, capital_figure},
    newest SH01 first."""
    horizon = as_of - datetime.timedelta(days=window_days)
    candidates = []
    scanned = 0
    start_index = 0
    while scanned < max_companies:
        page = client.advanced_search(
            incorporated_from=incorporated_from, sic_codes=sics,
            location=location, size=PAGE_SIZE, start_index=start_index)
        if not page:
            break
        start_index += len(page)
        for item in page:
            if scanned >= max_companies:
                break
            scanned += 1
            if progress and scanned % 25 == 0:
                progress(scanned)
            number = item.get("company_number")
            if not number:
                continue
            try:
                sh01s = ch.extract_sh01_events(
                    client.get_capital_filings(number))
            except Exception as exc:
                print("  warn: filing history for %s failed: %s"
                      % (number, exc))
                continue
            recent = [s for s in sh01s
                      if s["date"] and util.parse_iso(s["date"]) >= horizon]
            if not recent:
                continue
            latest = max(recent, key=lambda s: s["date"])
            office = ch.registered_office_text(item)
            region, _ = geo.locate(office)
            candidates.append({
                "name": item.get("company_name", "").title(),
                "number": number,
                "incorporated": item.get("date_of_creation"),
                "office": office,
                "region": region or "uk",
                "sh01_date": latest["date"],
                "capital_figure": latest["capital_figure"],
            })
        if len(page) < PAGE_SIZE:
            break   # a short page means the register ran out of matches
    # London first, then the rest of the UK, newest allotment first.
    candidates.sort(key=lambda c: c["sh01_date"], reverse=True)
    candidates.sort(key=lambda c: 0 if c["region"] == "london" else 1)
    return candidates, scanned


def render_report(candidates, scanned, as_of, window_days, max_companies):
    lines = [
        "# Companies House SH01 sweep, %s" % as_of,
        "",
        "%d candidate(s) with an SH01 allotment in the last %d days, from "
        "a sample of %d young companies (cap %d; the register holds far "
        "more, so run the sweep repeatedly rather than treating this as "
        "complete coverage)." % (len(candidates), window_days, scanned,
                                 max_companies),
        "",
        "A statement-of-capital figure is NOT the amount raised. Before "
        "adding a lead: confirm the entity, find the company site or a "
        "press source, then add name, stage, url, date, and this "
        "company_number to sources.yaml leads.",
        "",
    ]
    for c in candidates:
        lines.append("## %s (%s)" % (c["name"], c["number"]))
        lines.append("- Region: %s" % ("London" if c["region"] == "london"
                                       else "UK"))
        lines.append("- Registered office: %s" % (c["office"] or "unknown"))
        lines.append("- Incorporated: %s" % (c["incorporated"] or "unknown"))
        lines.append("- SH01 allotment: %s" % c["sh01_date"])
        lines.append("- Statement of capital: %s (NOT the amount raised)"
                     % (c["capital_figure"] or "not stated"))
        lines.append("- Register: %s" % (CH_COMPANY_URL % c["number"]))
        lines.append("")
    if not candidates:
        lines.append("No SH01 allotments inside the window in this sample.")
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m radar.chsweep", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--window", type=int, default=30,
                        help="SH01 lookback in days (default 30; the sieve "
                             "still applies the real recency gate later)")
    parser.add_argument("--max-companies", type=int, default=150,
                        help="filing histories to scan (default 150, "
                             "hard cap %d: each costs one API call)" % HARD_CAP)
    parser.add_argument("--incorporated-from", default=None,
                        metavar="YYYY-MM-DD",
                        help="only companies incorporated on or after this "
                             "date (default: 3 years before today)")
    parser.add_argument("--location", default="london",
                        help="registered-office filter (default london; "
                             "use '' to sweep the whole UK)")
    parser.add_argument("--sic", action="append", default=None,
                        metavar="CODE",
                        help="SIC code to include (repeatable; default: "
                             "the built-in tech set)")
    parser.add_argument("--as-of", default=None, metavar="YYYY-MM-DD",
                        help="treat this date as today (default: today)")
    parser.add_argument("--write", action="store_true",
                        help="also save reports/chsweep/<date>.md")
    args = parser.parse_args(argv)

    key = config.companies_house_key()
    if not key:
        print("chsweep: live mode needs COMPANIES_HOUSE_API_KEY in .env; "
              "see python -m radar.todo list")
        return 2

    as_of = util.parse_iso(args.as_of) if args.as_of else datetime.date.today()
    max_companies = min(args.max_companies, HARD_CAP)
    incorporated_from = args.incorporated_from or (
        as_of - datetime.timedelta(days=3 * 365)).isoformat()
    sics = args.sic or DEFAULT_SICS

    print("chsweep: sampling up to %d companies (SIC %s, incorporated from "
          "%s, location %r) for SH01s in the last %d days ..."
          % (max_companies, ",".join(sics), incorporated_from,
             args.location, args.window))

    client = ch.CompaniesHouseClient(key)
    candidates, scanned = sweep(
        client, as_of, args.window, incorporated_from, sics,
        args.location or None, max_companies,
        progress=lambda n: print("  ... %d scanned" % n))

    report = render_report(candidates, scanned, as_of, args.window,
                           max_companies)
    print()
    print(report)
    if args.write:
        out_dir = config.ROOT / "reports" / "chsweep"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / ("%s.md" % as_of)
        path.write_text(report)
        print("saved: %s" % path.relative_to(config.ROOT))
    print("Nothing was written to the database; add verified leads to "
          "sources.yaml and run python -m radar.ingest.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
