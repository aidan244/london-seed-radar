"""Live smoke tests: one real API call per source, for when keys exist.
Read-only; nothing is written to the database.

  python -m radar.smoke companies_house [--query monzo]
  python -m radar.smoke rss
  python -m radar.smoke ats <greenhouse|ashby|lever> <token>
"""

import argparse
import sys

from radar import ats, ch, config, rssfeeds


def smoke_companies_house(query):
    key = config.companies_house_key()
    if not key:
        print("COMPANIES_HOUSE_API_KEY missing from .env; see "
              "python -m radar.todo list")
        return 2
    client = ch.CompaniesHouseClient(key)
    hits = client.search_companies(query)
    if not hits:
        print("Search for %r returned nothing." % query)
        return 1
    top = hits[0]
    print("Top hit for %r: %s (%s)" % (query, top.get("title"),
                                       top.get("company_number")))
    filings = client.get_capital_filings(top["company_number"])
    sh01s = ch.extract_sh01_events(filings)
    print("Capital filings: %d, of which SH01 allotments: %d"
          % (len(filings), len(sh01s)))
    for event in sh01s[:3]:
        print("  SH01 %s (statement of capital: %s; NOT the amount raised)"
              % (event["date"], event["capital_figure"] or "n/a"))
    return 0


def smoke_rss():
    items = rssfeeds.load_live()
    print("Funding-shaped items across configured feeds: %d" % len(items))
    for item in items[:5]:
        print("  [%s] %s (%s, stage: %s)"
              % (item["source_name"], item["title"],
                 item["published_date"], item["stage"] or "?"))
    return 0 if items else 1


def smoke_ats(provider, token):
    result = ats.fetch(provider, token)
    print("%s board %r: %s, %d job(s)"
          % (provider, token, result["status"], len(result["jobs"])))
    for job in result["jobs"][:5]:
        print("  %s (%s)" % (job["title"], job["location"] or "?"))
    if result["status"] == "unverifiable":
        print("  endpoint 404s; if the hosted page renders, the org has "
              "disabled the public API. Treat as unverifiable, do not guess.")
    return 0 if result["status"] == "verified" else 1


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m radar.smoke", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="source", required=True)
    p_ch = sub.add_parser("companies_house")
    p_ch.add_argument("--query", default="monzo")
    sub.add_parser("rss")
    p_ats = sub.add_parser("ats")
    p_ats.add_argument("provider", choices=list(ats.PROVIDERS))
    p_ats.add_argument("token")
    args = parser.parse_args(argv)

    if args.source == "companies_house":
        return smoke_companies_house(args.query)
    if args.source == "rss":
        return smoke_rss()
    return smoke_ats(args.provider, args.token)


if __name__ == "__main__":
    sys.exit(main())
