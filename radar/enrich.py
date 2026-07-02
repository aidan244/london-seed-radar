"""Stage 3: enrich. For every sieved event: company one-liner, founders'
names and public backgrounds (company site and press only), a headcount
estimate with its source, and a live ATS hiring check.

No personal contact data, ever: no emails, no phone numbers, no
enrichment of personal details. Names, public roles, and public-record
backgrounds only.
"""

import argparse
import datetime
import json
import re
import sys

import requests

from radar import ats, config, db, domains, util

_TITLE_TAG = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_META_DESC = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)', re.IGNORECASE)
_FOUNDED_BY = re.compile(
    r"(?:founded|co-founded|started|launched)\s+(?:in \d{4} )?by\s+"
    r"(?P<names>[A-Z][\w'.-]+(?: [A-Z][\w'.-]+)+"
    r"(?:(?:,| and) [A-Z][\w'.-]+(?: [A-Z][\w'.-]+)+)*)")


def _load_fixture(company_number):
    path = config.FIXTURES_DIR / "enrichment" / ("%s.json" % company_number)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _fetch_homepage_one_liner(url):
    """Best effort, live mode only: meta description or title tag."""
    try:
        resp = requests.get(url, timeout=10,
                            headers={"User-Agent": "london-seed-radar/0.1"})
        if resp.status_code >= 400:
            return None, None
    except requests.RequestException:
        return None, None
    m = _META_DESC.search(resp.text) or _TITLE_TAG.search(resp.text)
    if not m:
        return None, None
    text = re.sub(r"\s+", " ", m.group(1)).strip()[:200]
    return (text or None), "homepage meta (verify before featuring)"


def _founders_from_press(evidence):
    """Best effort, live mode only: 'founded by X and Y' in press snippets."""
    found = []
    for row in evidence:
        text = " ".join(filter(None, [row["title"], row["snippet"]]))
        m = _FOUNDED_BY.search(text)
        if not m:
            continue
        for name in re.split(r",| and ", m.group("names")):
            name = name.strip()
            if name and name not in [f["name"] for f in found]:
                found.append({"name": name, "role": "co-founder",
                              "background": None, "source_url": row["url"]})
    return found


# Public hosted board pages, one per provider, used to corroborate that a
# guessed slug's board actually belongs to the company.
_HOSTED_PAGES = {
    "greenhouse": "https://boards.greenhouse.io/%s",
    "ashby": "https://jobs.ashbyhq.com/%s",
    "lever": "https://jobs.lever.co/%s",
}


def _board_belongs_to(company, provider, token, page_fetch=None):
    """A 200 from a guessed slug is not proof the board is this company's:
    two firms can share the same slug guess, and accepting the first hit
    would publish an unrelated company's postings as a verified hiring
    signal. Corroborate against the provider's public hosted page with the
    same honesty guardrail domains.py uses for websites."""
    fetch = page_fetch or domains._fetch
    html = fetch(_HOSTED_PAGES[provider] % token)
    return html is not None and domains.corroborates(html, company["name"])


def _discover_ats(company, fixtures, page_fetch=None):
    """Resolve an ATS board: explicit override, then slug probing.
    All three providers expose open JSON endpoints; a 404 just means
    the slug is not theirs (or, for Ashby, the public API is disabled).
    A human-verified ats_override is trusted as-is; a probed slug must
    also corroborate as belonging to this company. Fixture mode trusts
    the recorded fixtures (they are curated)."""
    overrides = config.load_sources().get("ats_overrides") or {}
    override = overrides.get(company["normalized_name"])
    if override:
        result = ats.fetch(override["provider"], override["token"], fixtures)
        return override["provider"], override["token"], result
    slugs = []
    if company["domain"]:
        slugs.append(company["domain"].split(".")[0])
    slugs.append(util.slugify(company["name"]).replace("-", ""))
    for provider in ats.PROVIDERS:
        for slug in dict.fromkeys(slugs):
            result = ats.fetch(provider, slug, fixtures)
            if result["status"] != "verified":
                continue
            if fixtures or _board_belongs_to(company, provider, slug,
                                             page_fetch):
                return provider, slug, result
    return None, None, None


def _record_jobs(conn, company_id, provider, jobs, seen_at=None):
    """Insert new postings and stamp last_seen on every posting this fetch
    returned. Postings absent from the latest fetch keep their older
    last_seen, which is how publish ages closed roles out of the site and
    dataset without deleting the history."""
    seen_at = seen_at or datetime.datetime.now().isoformat(timespec="seconds")
    for job in jobs:
        conn.execute(
            "INSERT OR IGNORE INTO jobs "
            "(company_id, title, location, url, ats_provider) "
            "VALUES (?, ?, ?, ?, ?)",
            (company_id, job["title"], job["location"], job["url"], provider))
        conn.execute(
            "UPDATE jobs SET last_seen = ? WHERE company_id = ? AND url = ?",
            (seen_at, company_id, job["url"]))


def refresh_jobs(conn, fixtures=False):
    """Re-fetch the verified ATS boards of featured and published companies
    and stamp what is live now, so a later publish exports current hiring
    rather than launch-day postings. On-demand only; a fetch error leaves
    the stored postings untouched rather than wiping them."""
    companies = conn.execute(
        "SELECT DISTINCT c.* FROM companies c "
        "JOIN funding_events fe ON fe.company_id = c.id "
        "WHERE fe.status IN ('featured','published') "
        "AND c.ats_status = 'verified' AND c.ats_provider IS NOT NULL "
        "ORDER BY c.name").fetchall()
    refreshed = 0
    for company in companies:
        result = ats.fetch(company["ats_provider"], company["ats_token"],
                           fixtures)
        if result["status"] != "verified":
            print("  %-28s board not verifiable right now (%s); postings "
                  "left as they were" % (company["name"], result["status"]))
            continue
        _record_jobs(conn, company["id"], company["ats_provider"],
                     result["jobs"])
        refreshed += 1
        print("  %-28s %d live role(s)" % (company["name"],
                                           len(result["jobs"])))
    return refreshed


def enrich_company(conn, company, evidence, fixtures):
    # Two override sources feed the same shape: the recorded test fixtures
    # (only under --fixtures) and the curated live-mode files under
    # enrichment/. Curated wins on a shared key, so a hand- or Clay-verified
    # fact beats both the fixture and the auto-derived fallback.
    fixture = _load_fixture(company["company_number"]) if fixtures else {}
    curated = config.load_curated_enrichment(company["company_number"])
    override = {**fixture, **curated}
    notes = []

    one_liner = override.get("one_liner")
    one_liner_source = override.get("one_liner_source")
    if not one_liner and not fixtures and company["website"]:
        one_liner, one_liner_source = _fetch_homepage_one_liner(company["website"])
    if not one_liner and evidence:
        one_liner = (evidence[-1]["snippet"] or "")[:200] or None
        one_liner_source = "press summary (rewrite before featuring)"

    founders = override.get("founders") or _founders_from_press(evidence)
    written = 0
    for founder in founders:
        # Hard rule 2, enforced at the write: a scraped role line or a
        # curated typo carrying an email or phone shape never lands.
        if any(util.looks_like_contact_data(founder.get(k))
               for k in ("name", "role", "background")):
            print("  warn: founder entry for %s looks like it carries "
                  "contact data; skipped" % company["name"])
            continue
        conn.execute(
            "INSERT OR IGNORE INTO founders "
            "(company_id, name, role, background, source_url) "
            "VALUES (?, ?, ?, ?, ?)",
            (company["id"], founder["name"], founder.get("role"),
             founder.get("background"), founder.get("source_url")))
        written += 1
    notes.append("%d founder(s)" % written)

    headcount = override.get("headcount_estimate") or "unknown"
    headcount_source = override.get("headcount_source") or \
        ("not estimated; check the team page" if headcount == "unknown" else None)

    if override.get("ats"):
        provider, token = override["ats"]["provider"], override["ats"]["token"]
        result = ats.fetch(provider, token, fixtures)
    elif "ats" in override:
        provider = token = result = None
    else:
        provider, token, result = _discover_ats(company, fixtures)

    jobs_count = 0
    if result is None:
        ats_status = "none"
        notes.append("no ATS board found")
    elif result["status"] == "verified":
        ats_status = "verified"
        _record_jobs(conn, company["id"], provider, result["jobs"])
        jobs_count = len(result["jobs"])
        notes.append("%d live role(s) on %s" % (jobs_count, provider))
    else:
        ats_status = "unverifiable"
        notes.append("%s board exists but the public API is disabled; "
                     "treat hiring as unverifiable" % (provider or "ATS"))

    conn.execute(
        "UPDATE companies SET one_liner = ?, one_liner_source = ?, "
        "headcount_estimate = ?, headcount_source = ?, ats_provider = ?, "
        "ats_token = ?, ats_status = ? WHERE id = ?",
        (one_liner, one_liner_source, headcount, headcount_source,
         provider, token, ats_status, company["id"]))
    return notes


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m radar.enrich", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    util.add_common_args(parser, as_of=False)
    parser.add_argument("--refresh-jobs", action="store_true",
                        help="re-fetch the verified ATS boards of featured "
                             "and published companies so publish exports "
                             "current hiring, then exit")
    args = parser.parse_args(argv)

    conn = db.connect(args.db)
    db.init_db(conn)

    if args.refresh_jobs:
        refreshed = refresh_jobs(conn, args.fixtures)
        conn.commit()
        print("enrich: refreshed job postings for %d compan%s"
              % (refreshed, "y" if refreshed == 1 else "ies"))
        if refreshed:
            print("Next: python -m radar.publish (exports only postings "
                  "seen by each company's latest fetch)")
        return 0

    events = conn.execute(
        "SELECT * FROM funding_events WHERE status = 'sieved' "
        "ORDER BY event_date").fetchall()

    for event in events:
        company = db.get_company(conn, event["company_id"])
        evidence = db.event_evidence(conn, event["id"])
        notes = enrich_company(conn, company, evidence, args.fixtures)
        db.advance_status(conn, event["id"], "enriched")
        print("  %-28s %s" % (company["name"], "; ".join(notes)))
    conn.commit()

    print("enrich: %d event(s) enriched" % len(events))
    if events:
        print("Next: python -m radar.issue")
    return 0


if __name__ == "__main__":
    sys.exit(main())
