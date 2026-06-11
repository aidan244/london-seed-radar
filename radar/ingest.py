"""Stage 1: ingest. Pull Companies House capital filings and RSS press
items, normalise them into candidate funding events with status
'discovered'. Runs, writes, exits.

Live mode needs COMPANIES_HOUSE_API_KEY in .env and refuses to run
without it, pointing at the relevant human todo. Fixture mode
(--fixtures) runs entirely from tests/fixtures/.
"""

import argparse
import datetime
import sys

from radar import ch, config, db, rssfeeds, util

# A filing and a press item this many days apart still describe one round.
MERGE_WINDOW_DAYS = 45
# Live mode ignores filings older than this; the sieve enforces the real
# recency gate, this just keeps old history out of the database.
LIVE_FILING_HORIZON_DAYS = 90

CH_PUBLIC_URL = ("https://find-and-update.company-information.service.gov.uk"
                 "/company/%s/filing-history")


def find_or_create_event(conn, company_id, event_date, source_mode):
    """Match an observation to an existing event for the same company
    within MERGE_WINDOW_DAYS, or create a new discovered event.

    Dropped and published events match too: re-ingesting the same filing
    or article must merge into the existing event, never duplicate it or
    resurrect a dropped one (statuses only move forward)."""
    target = util.parse_iso(event_date)
    rows = conn.execute(
        "SELECT * FROM funding_events WHERE company_id = ?", (company_id,),
    ).fetchall()
    for row in rows:
        delta = abs((util.parse_iso(row["event_date"]) - target).days)
        if delta <= MERGE_WINDOW_DAYS:
            return row["id"], False
    cur = conn.execute(
        "INSERT INTO funding_events (company_id, event_date, source_mode) "
        "VALUES (?, ?, ?)",
        (company_id, event_date, source_mode),
    )
    return cur.lastrowid, True


def _update_event(conn, event_id, **fields):
    updates = {k: v for k, v in fields.items() if v is not None}
    if not updates:
        return
    assignments = ", ".join("%s = ?" % k for k in updates)
    conn.execute("UPDATE funding_events SET %s WHERE id = ?" % assignments,
                 list(updates.values()) + [event_id])


def ingest_filings(conn, profiles, filings_for, as_of, source_mode):
    """profiles: {number: profile}; filings_for: number -> capital filing items."""
    created = updated = filers = 0
    horizon = as_of - datetime.timedelta(days=LIVE_FILING_HORIZON_DAYS)
    for number, profile in profiles.items():
        sh01s = ch.extract_sh01_events(filings_for(number))
        if not sh01s:
            continue
        filers += 1
        company_id = db.upsert_company(
            conn, profile["company_name"].title(), company_number=number,
            location_text=ch.registered_office_text(profile),
            incorporated_on=profile.get("date_of_creation"),
        )
        for filing in sh01s:
            if source_mode == "live" and util.parse_iso(filing["date"]) < horizon:
                continue
            event_id, is_new = find_or_create_event(
                conn, company_id, filing["date"], source_mode)
            created += is_new
            updated += not is_new
            # Prefer the filing's allotment date as the event date.
            conn.execute(
                "UPDATE funding_events SET filing_id = ?, event_date = ? "
                "WHERE id = ? AND filing_id IS NULL",
                (filing["transaction_id"], filing["date"], event_id),
            )
            snippet = "SH01 allotment of shares"
            if filing.get("capital_figure"):
                snippet += ("; statement of capital %s GBP (NOT the amount "
                            "raised; check press)" % filing["capital_figure"])
            db.add_evidence(
                conn, event_id, "filing", "Companies House",
                CH_PUBLIC_URL % number, title="SH01 %s" % filing["date"],
                snippet=snippet, published_date=filing["date"],
            )
    return created, updated, filers


def _match_company_number(item_name, profiles):
    norm = db.normalize_name(item_name)
    for number, profile in profiles.items():
        if db.normalize_name(profile["company_name"]) == norm:
            return number
    return None


def ingest_press(conn, items, profiles, source_mode):
    created = updated = 0
    for item in items:
        if not item.get("published_date"):
            continue
        number = _match_company_number(item["company_name"], profiles)
        profile = profiles.get(number)
        company_id = db.upsert_company(
            conn, item["company_name"], company_number=number,
            location_text=ch.registered_office_text(profile) if profile else None,
            incorporated_on=profile.get("date_of_creation") if profile else None,
        )
        # The headline casing ("Quillstone AI") beats the title-cased
        # register name ("Quillstone Ai Ltd") as a display name.
        conn.execute("UPDATE companies SET name = ? WHERE id = ?",
                     (item["company_name"], company_id))
        event_id, is_new = find_or_create_event(
            conn, company_id, item["published_date"], source_mode)
        created += is_new
        updated += not is_new
        _update_event(conn, event_id, stage=item.get("stage"),
                      amount_gbp=item.get("amount_gbp"),
                      amount_source=("press: %s" % item["source_name"]
                                     if item.get("amount_gbp") else None))
        db.add_evidence(conn, event_id, "press", item["source_name"],
                        item["url"], title=item["title"],
                        snippet=item["summary"][:600],
                        published_date=item["published_date"])
    return created, updated


def _live_profiles_for_items(client, items, watchlist):
    """Resolve press candidates and watchlist numbers to CH profiles."""
    profiles = {}
    for number in watchlist:
        try:
            profile = client.get_profile(str(number))
            profiles[profile["company_number"]] = profile
        except Exception as exc:
            print("  warn: watchlist %s lookup failed: %s" % (number, exc))
    for item in items:
        norm = db.normalize_name(item["company_name"])
        try:
            for hit in client.search_companies(item["company_name"]):
                if db.normalize_name(hit.get("title", "")) == norm:
                    profiles[hit["company_number"]] = client.get_profile(
                        hit["company_number"])
                    break
        except Exception as exc:
            print("  warn: search for %r failed: %s" % (item["company_name"], exc))
    return profiles


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m radar.ingest", description=__doc__)
    util.add_common_args(parser)
    args = parser.parse_args(argv)
    as_of = util.resolve_as_of(args)

    conn = db.connect(args.db)
    db.init_db(conn)

    if args.fixtures:
        profiles = ch.fixture_profiles()
        filings_for = ch.fixture_capital_filings
        items = rssfeeds.load_fixtures()
        mode = "fixture"
    else:
        key = config.companies_house_key()
        if not key:
            todo = conn.execute(
                "SELECT id, task FROM human_todos WHERE status = 'pending' "
                "AND task LIKE '%Companies House%'").fetchone()
            print("ingest: live mode needs COMPANIES_HOUSE_API_KEY in .env "
                  "and refuses to run without it.")
            if todo:
                print("Pending human todo #%d: %s" % (todo["id"], todo["task"]))
            print("Run 'python -m radar.todo list' for the setup checklist, "
                  "or use --fixtures for an offline run.")
            return 2
        client = ch.CompaniesHouseClient(key)
        print("Fetching RSS feeds from sources.yaml ...")
        items = rssfeeds.load_live()
        watchlist = config.load_sources().get("watchlist_company_numbers") or []
        print("Resolving %d press candidates against Companies House ..."
              % len(items))
        profiles = _live_profiles_for_items(client, items, watchlist)
        filings_for = client.get_capital_filings
        mode = "live"

    fc, fu, filers = ingest_filings(conn, profiles, filings_for, as_of, mode)
    pc, pu = ingest_press(conn, items, profiles, mode)
    conn.commit()

    total = conn.execute(
        "SELECT COUNT(*) c FROM funding_events WHERE status = 'discovered'"
    ).fetchone()["c"]
    print("ingest (%s mode, as of %s):" % (mode, as_of))
    print("  press candidates: %d" % len(items))
    print("  companies with SH01 capital filings: %d" % filers)
    print("  events created: %d, corroborated/merged: %d"
          % (fc + pc, fu + pu))
    print("  events now awaiting sieve: %d" % total)
    print("Next: python -m radar.sieve%s" % (" --fixtures" if args.fixtures else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
