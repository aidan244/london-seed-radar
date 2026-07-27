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

from radar import ch, config, db, leads, rssfeeds, util

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
    """Set non-None fields on an event, unless it is terminal. A published
    or dropped event still absorbs repeat observations (the merge in
    find_or_create_event matched it, and evidence may still be recorded),
    but its stage, amount, and date are locked: the published record must
    never silently change under a routine re-ingest."""
    updates = {k: v for k, v in fields.items() if v is not None}
    if not updates:
        return
    row = conn.execute("SELECT status FROM funding_events WHERE id = ?",
                       (event_id,)).fetchone()
    if row is None or row["status"] in db.TERMINAL_STATUSES:
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
            # Prefer the filing's allotment date as the event date, but
            # never rewrite a terminal event's record (same lock as
            # _update_event).
            conn.execute(
                "UPDATE funding_events SET filing_id = ?, event_date = ? "
                "WHERE id = ? AND filing_id IS NULL "
                "AND status NOT IN (%s)"
                % ",".join("?" * len(db.TERMINAL_STATUSES)),
                [filing["transaction_id"], filing["date"], event_id]
                + sorted(db.TERMINAL_STATUSES),
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


def ingest_press(conn, items, profiles, source_mode, pinned_brands=None):
    pinned_brands = pinned_brands or {}
    created = updated = 0
    for item in items:
        if not item.get("published_date"):
            continue
        # A lead's human-verified company_number wins over a name search,
        # so a brand (Conduct) resolves to its real entity (CONDUCT AI LTD)
        # rather than a same-name company at the wrong UK address. A brand
        # another lead pinned wins too, so a name-only press item that shares
        # it (an RSS mention of Humanoid) merges into the pinned entity rather
        # than resolving an unrelated same-name company by search.
        number = (item.get("company_number")
                  or pinned_brands.get(db.normalize_name(item["company_name"]))
                  or _match_company_number(item["company_name"], profiles))
        profile = profiles.get(number)
        company_id = db.upsert_company(
            conn, item["company_name"], company_number=number,
            location_text=ch.registered_office_text(profile) if profile else None,
            incorporated_on=profile.get("date_of_creation") if profile else None,
        )
        # The headline casing ("Quillstone AI") beats the title-cased
        # register name ("Quillstone Ai Ltd") as a display name. Move the
        # normalized_name with it so brand-keyed lookups (website_overrides,
        # ats_overrides) resolve: a company resolved by number can have been
        # created under its register name (CONDUCT AI LTD -> "conduct ai")
        # while the override is keyed by the brand ("conduct").
        conn.execute("UPDATE companies SET name = ?, normalized_name = ? "
                     "WHERE id = ?",
                     (item["company_name"],
                      db.normalize_name(item["company_name"]), company_id))
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


def _live_profiles_for_items(client, items, watchlist, pinned_brands=None):
    """Resolve press candidates and watchlist numbers to CH profiles.

    A brand a lead pins with an explicit company_number is resolved only
    through that number (fetched via the watchlist below); the per-item name
    search is skipped for it, so a same-name company never sneaks a second,
    wrong-entity profile in beside the pinned one (the Humanoid collision: a
    generic name matched an unrelated active company). The name search also
    accepts active companies only, so a dissolved same-name shell is never
    resolved as a current raise (the Kord and Polysense shells)."""
    pinned_brands = pinned_brands or {}
    profiles = {}
    for number in watchlist:
        try:
            profile = client.get_profile(str(number))
            profiles[profile["company_number"]] = profile
        except Exception as exc:
            print("  warn: watchlist %s lookup failed: %s" % (number, exc))
    for item in items:
        norm = db.normalize_name(item["company_name"])
        if norm in pinned_brands:
            continue  # already fetched via its pinned company_number
        try:
            for hit in client.search_companies(item["company_name"]):
                if (db.normalize_name(hit.get("title", "")) == norm
                        and hit.get("company_status") == "active"):
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
    sources = config.load_sources()

    # Scout shortlists and manual leads join the press candidates as
    # ordinary items; the four gates verify them locally like any other.
    lead_items = leads.load_leads(config.ROOT, sources)

    # Brands a lead pins with an explicit, human-verified company_number.
    # Only leads carry a number, so these are the brands that must resolve to
    # that exact entity: a same-name company (the unrelated HUMANOID LTD that
    # a generic RSS mention matched) must never enter beside the pinned one.
    pinned_brands = {db.normalize_name(i["company_name"]): str(i["company_number"])
                     for i in lead_items if i.get("company_number")}

    if args.fixtures:
        profiles = ch.fixture_profiles()
        filings_for = ch.fixture_capital_filings
        items = rssfeeds.load_fixtures() + lead_items
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
        items = rssfeeds.load_live() + lead_items
        # Watchlist plus any company numbers leads carry, so an explicitly
        # resolved entity's profile (and its SH01 filings) is fetched too.
        watchlist = list(dict.fromkeys(
            (sources.get("watchlist_company_numbers") or [])
            + [i["company_number"] for i in items if i.get("company_number")]))
        print("Resolving %d candidates against Companies House ..."
              % len(items))
        profiles = _live_profiles_for_items(client, items, watchlist,
                                            pinned_brands)
        filings_for = client.get_capital_filings
        mode = "live"

    fc, fu, filers = ingest_filings(conn, profiles, filings_for, as_of, mode)
    pc, pu = ingest_press(conn, items, profiles, mode, pinned_brands)
    conn.commit()

    total = conn.execute(
        "SELECT COUNT(*) c FROM funding_events WHERE status = 'discovered'"
    ).fetchone()["c"]
    print("ingest (%s mode, as of %s):" % (mode, as_of))
    print("  press candidates: %d (incl. %d scout/manual leads)"
          % (len(items), len(lead_items)))
    print("  companies with SH01 capital filings: %d" % filers)
    print("  events created: %d, corroborated/merged: %d"
          % (fc + pc, fu + pu))
    print("  events now awaiting sieve: %d" % total)
    print("Next: python -m radar.sieve%s" % (" --fixtures" if args.fixtures else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
