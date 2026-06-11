"""Stage 3: enrich. For every sieved event: company one-liner, founders'
names and public backgrounds (company site and press only), a headcount
estimate with its source, and a live ATS hiring check.

No personal contact data, ever: no emails, no phone numbers, no
enrichment of personal details. Names, public roles, and public-record
backgrounds only.
"""

import argparse
import json
import re
import sys

import requests

from radar import ats, config, db, util

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


def _discover_ats(company, fixtures):
    """Resolve an ATS board: explicit override, then slug probing.
    All three providers expose open JSON endpoints; a 404 just means
    the slug is not theirs (or, for Ashby, the public API is disabled)."""
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
            if result["status"] == "verified":
                return provider, slug, result
    return None, None, None


def enrich_company(conn, company, evidence, fixtures):
    fixture = _load_fixture(company["company_number"]) if fixtures else {}
    notes = []

    one_liner = fixture.get("one_liner")
    one_liner_source = fixture.get("one_liner_source")
    if not one_liner and not fixtures and company["website"]:
        one_liner, one_liner_source = _fetch_homepage_one_liner(company["website"])
    if not one_liner and evidence:
        one_liner = (evidence[-1]["snippet"] or "")[:200] or None
        one_liner_source = "press summary (rewrite before featuring)"

    founders = fixture.get("founders") or _founders_from_press(evidence)
    for founder in founders:
        conn.execute(
            "INSERT OR IGNORE INTO founders "
            "(company_id, name, role, background, source_url) "
            "VALUES (?, ?, ?, ?, ?)",
            (company["id"], founder["name"], founder.get("role"),
             founder.get("background"), founder.get("source_url")))
    notes.append("%d founder(s)" % len(founders))

    headcount = fixture.get("headcount_estimate") or "unknown"
    headcount_source = fixture.get("headcount_source") or \
        ("not estimated; check the team page" if headcount == "unknown" else None)

    if fixture.get("ats"):
        provider, token = fixture["ats"]["provider"], fixture["ats"]["token"]
        result = ats.fetch(provider, token, fixtures)
    elif "ats" in fixture:
        provider = token = result = None
    else:
        provider, token, result = _discover_ats(company, fixtures)

    jobs_count = 0
    if result is None:
        ats_status = "none"
        notes.append("no ATS board found")
    elif result["status"] == "verified":
        ats_status = "verified"
        for job in result["jobs"]:
            conn.execute(
                "INSERT OR IGNORE INTO jobs "
                "(company_id, title, location, url, ats_provider) "
                "VALUES (?, ?, ?, ?, ?)",
                (company["id"], job["title"], job["location"], job["url"],
                 provider))
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
    args = parser.parse_args(argv)

    conn = db.connect(args.db)
    db.init_db(conn)
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
