"""Stage 2: sieve. Apply the four gates to every discovered event.
Every candidate passes or is dropped with a recorded reason.

Gates, in order:
  1. geography: a London marker, matched on word boundaries only.
  2. stage: pre-seed, seed, or Series A.
  3. recency: event date inside the lookback window (default 14 days).
  4. reality: live web presence plus a corroborated funding event
     (Companies House filing or at least one press source).

Dropping is terminal, so run --dry-run first when working live; if a
real company fails the reality gate only because its website is not
known yet, add it to website_overrides in sources.yaml and re-run.
"""

import argparse
import datetime
import json
import sys

import requests

from radar import config, db, geo, stages, util


def _load_enrichment_fixture(company_number):
    if not company_number:
        return {}
    path = config.FIXTURES_DIR / "enrichment" / ("%s.json" % company_number)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _check_website_live(url):
    try:
        resp = requests.get(url, timeout=10, allow_redirects=True,
                            headers={"User-Agent": "london-seed-radar/0.1"})
        return resp.status_code < 400
    except requests.RequestException:
        return False


def resolve_website(company, fixtures):
    """Return (url, reachable) for the reality gate.
    Fixture mode reads the recorded enrichment file; live mode uses the
    company row or website_overrides in sources.yaml, then fetches it."""
    if fixtures:
        fixture = _load_enrichment_fixture(company["company_number"])
        url = fixture.get("website")
        return url, bool(url and fixture.get("website_reachable"))
    overrides = config.load_sources().get("website_overrides") or {}
    url = company["website"] or overrides.get(company["normalized_name"])
    if not url:
        return None, False
    return url, _check_website_live(url)


def evaluate_gates(company, event, evidence, as_of, window_days, fixtures):
    """Run the four gates. Returns (passed, gates, drop_reason).
    gates is an ordered list of {gate, passed, detail} dicts."""
    gates = []

    def record(gate, passed, detail):
        gates.append({"gate": gate, "passed": passed, "detail": detail})
        return passed

    # 1. Geography. Registered office plus press text, word boundaries only.
    text = " ".join(filter(None, [company["location_text"]]
                           + [e["title"] for e in evidence]
                           + [e["snippet"] for e in evidence]))
    marker = geo.find_london_marker(text)
    if not record("geography", marker is not None,
                  "London marker: %s" % marker if marker
                  else "no London marker found in registered office or press"):
        return False, gates, "geography: " + gates[-1]["detail"]

    # 2. Stage.
    stage = event["stage"]
    if stage in stages.IN_SCOPE_STAGES:
        record("stage", True, stage)
    else:
        detail = ("round stage %s is out of scope" % stage if stage
                  else "stage unknown: no pre-seed, seed, or Series A "
                       "keyword in any evidence")
        record("stage", False, detail)
        return False, gates, "stage: " + detail

    # 3. Recency.
    cutoff = as_of - datetime.timedelta(days=window_days)
    event_date = util.parse_iso(event["event_date"])
    if not record("recency", event_date >= cutoff,
                  "event date %s vs %d-day window starting %s"
                  % (event_date, window_days, cutoff)):
        return False, gates, "recency: " + gates[-1]["detail"]

    # 4. Reality: live web presence and a corroborated funding event.
    corroborated = any(e["kind"] in ("filing", "press") for e in evidence)
    website, reachable = resolve_website(company, fixtures)
    if not corroborated:
        record("reality", False, "no filing or press evidence on record")
        return False, gates, "reality: " + gates[-1]["detail"]
    if not reachable:
        detail = ("website %s is not reachable" % website if website
                  else "no website found; add it to website_overrides in "
                       "sources.yaml and re-run sieve")
        record("reality", False, detail)
        return False, gates, "reality: " + detail
    record("reality", True, "website %s live; %d evidence source(s)"
           % (website, len(evidence)))
    return True, gates, None


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m radar.sieve", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    util.add_common_args(parser)
    parser.add_argument("--window", type=int, default=None,
                        help="lookback window in days (default from sources.yaml)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report gate outcomes without writing anything")
    args = parser.parse_args(argv)
    as_of = util.resolve_as_of(args)
    window = args.window or config.lookback_days()

    conn = db.connect(args.db)
    db.init_db(conn)
    events = conn.execute(
        "SELECT fe.*, c.name AS company_name FROM funding_events fe "
        "JOIN companies c ON c.id = fe.company_id "
        "WHERE fe.status = 'discovered' ORDER BY fe.event_date").fetchall()

    passed = dropped = 0
    for event in events:
        company = db.get_company(conn, event["company_id"])
        evidence = db.event_evidence(conn, event["id"])
        ok, gates, drop_reason = evaluate_gates(
            company, event, evidence, as_of, window, args.fixtures)
        verdict = "PASS" if ok else "DROP"
        print("  [%s] %-28s %s" % (verdict, event["company_name"],
                                   drop_reason or "all four gates passed"))
        if args.dry_run:
            continue
        conn.execute("UPDATE funding_events SET gates_json = ? WHERE id = ?",
                     (json.dumps(gates), event["id"]))
        if ok:
            # The reality gate verified the website; persist it.
            website, _ = resolve_website(company, args.fixtures)
            if website:
                conn.execute(
                    "UPDATE companies SET website = ?, website_status = 'live', "
                    "domain = COALESCE(domain, ?) WHERE id = ?",
                    (website, util.domain_of(website), company["id"]))
            db.advance_status(conn, event["id"], "sieved")
            passed += 1
        else:
            db.advance_status(conn, event["id"], "dropped", drop_reason)
            dropped += 1
    conn.commit()

    label = "dry run, nothing written" if args.dry_run else \
        "%d passed, %d dropped" % (passed, dropped)
    print("sieve (as of %s, %d-day window): %d candidates; %s"
          % (as_of, window, len(events), label))
    if passed:
        print("Next: python -m radar.enrich%s"
              % (" --fixtures" if args.fixtures else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
