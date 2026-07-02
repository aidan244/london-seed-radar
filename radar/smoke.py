"""Live smoke tests: one real API call per source, for when keys exist.
Read-only; nothing is written to the database.

  python -m radar.smoke companies_house [--query monzo]
  python -m radar.smoke rss [--from-dir PATH]
  python -m radar.smoke ats <greenhouse|ashby|lever> <token>
"""

import argparse
import pathlib
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


def smoke_rss(from_dir=None):
    if from_dir:
        items = rssfeeds.load_from_dir(pathlib.Path(from_dir))
        print("Triaged saved feeds in %s" % from_dir)
    else:
        result = rssfeeds.fetch_live()
        items = result["items"]
        print("%-16s %-8s %8s %8s" % ("feed", "status", "entries", "funding"))
        for f in result["feeds"]:
            status = f["error"] or (f["status"] if f["status"] is not None else "ok")
            print("  %-14s %-8s %8d %8d"
                  % (f["name"][:14], status, f["entries"], f["funding_items"]))
    print("Funding-shaped items: %d" % len(items))
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
    p_rss = sub.add_parser("rss")
    p_rss.add_argument("--from-dir", default=None, metavar="PATH",
                       help="triage saved feed files (*.xml) in PATH instead "
                            "of fetching live; for the WebFetch-based scout")
    p_ats = sub.add_parser("ats")
    p_ats.add_argument("provider", choices=list(ats.PROVIDERS))
    p_ats.add_argument("token")
    args = parser.parse_args(argv)

    # A smoke test that stack-traces on a timeout has failed at its one
    # job; report the failure and exit nonzero instead.
    try:
        if args.source == "companies_house":
            return smoke_companies_house(args.query)
        if args.source == "rss":
            return smoke_rss(args.from_dir)
        return smoke_ats(args.provider, args.token)
    except Exception as exc:
        print("smoke %s failed: %s" % (args.source, exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
