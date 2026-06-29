"""Pre-sieve domain resolution: give discovered companies a website so the
reality gate has something to check.

Most press and scout leads carry a company name but no website, and
Companies House gives a registered office, not a URL. Without a website the
reality gate drops the candidate, so real London raises die for want of a
link nobody added to website_overrides. This step guesses likely domains
from the company name, fetches each, and keeps the first that is live AND
whose page names the company, so a parked or for-sale domain is not taken
as a live site. It writes the verified URL onto the company row, where the
sieve's resolve_website already looks.

Best effort, not infallible: a same-name company in another country can
still pass a pure name match (a "Zaro" bakery for a "Zaro" startup), so the
geography gate and human review remain the backstop, and a human-curated
website_override always wins over a value resolved here. A company we cannot
corroborate is left without a website and still drops. Run it between
ingest and sieve.

  python -m radar.domains
"""

import argparse
import re
import sys

import requests

from radar import db, util

# Common startup TLDs, tried in rough order of likelihood. The .com and the
# first slug come first, so a name that is just its domain resolves in one
# fetch.
TLDS = (".com", ".ai", ".io", ".co", ".xyz", ".so", ".app", ".tech")
TIMEOUT = 6
_TAGS = re.compile(r"<[^>]+>")
# Markers of a registrar holding page or a domain marketplace, so a parked
# or for-sale domain is never taken as a live company site. A desirable
# short name is often parked (superlight.com sat on a Grails.com listing),
# and the name still appears on the page, so the name match alone is not
# enough; these patterns veto it.
_PARKED = re.compile(
    r"(this )?domain( name)?s? (is |are )?(for sale|available)|"
    r"available for sale or other proposals|buy this domain|"
    r"domain (name )?(broker|marketplace)|premium domains?|"
    r"strategic-grade domain|parked (free|page)|sedoparking|hugedomains|"
    r"afternic|grails\.com|dan\.com|godaddy", re.IGNORECASE)


def candidate_domains(name):
    """Likely URLs for a company name: the slug with and without a hyphen,
    across common TLDs, most likely first. 'Record OS' yields recordos.* and
    record-os.*; 'Flagright' yields flagright.*."""
    norm = db.normalize_name(name)
    if not norm:
        return []
    nospace = norm.replace(" ", "")
    hyphen = norm.replace(" ", "-")
    slugs = [nospace] if nospace == hyphen else [nospace, hyphen]
    return ["https://%s%s" % (slug, tld) for tld in TLDS for slug in slugs]


def corroborates(html, name):
    """True when the page plausibly belongs to this company: not a parked
    page, and the brand string (or every meaningful name token) appears in
    the text. This is the honesty guardrail that keeps a wrong same-name
    site out of the reality gate."""
    text = _TAGS.sub(" ", html or "").lower()
    if not text.strip() or _PARKED.search(text):
        return False
    norm = db.normalize_name(name)
    if norm and norm.replace(" ", "") in text.replace(" ", ""):
        return True
    tokens = [t for t in norm.split() if len(t) > 2]
    return bool(tokens) and all(t in text for t in tokens)


def _fetch(url):
    try:
        resp = requests.get(url, timeout=TIMEOUT, allow_redirects=True,
                            headers={"User-Agent": "london-seed-radar/0.1"})
        return resp.text if resp.status_code < 400 else None
    except requests.RequestException:
        return None


def resolve_website(name, fetch=None):
    """First live, corroborated domain for a company name, or None."""
    fetch = fetch or _fetch
    for url in candidate_domains(name):
        html = fetch(url)
        if html is not None and corroborates(html, name):
            return url
    return None


def resolve_discovered(conn, fetch=None):
    """Set a verified website on every discovered company that lacks one.
    Returns [(name, url_or_None)] for reporting. Changes no statuses and
    never overwrites a website already on record."""
    rows = conn.execute(
        "SELECT DISTINCT c.id, c.name FROM companies c "
        "JOIN funding_events fe ON fe.company_id = c.id "
        "WHERE fe.status = 'discovered' "
        "AND (c.website IS NULL OR c.website = '')"
    ).fetchall()
    out = []
    for row in rows:
        url = resolve_website(row["name"], fetch)
        if url:
            conn.execute(
                "UPDATE companies SET website = ?, website_status = 'live' "
                "WHERE id = ?", (url, row["id"]))
            dom = util.domain_of(url)
            taken = dom and conn.execute(
                "SELECT 1 FROM companies WHERE domain = ? AND id <> ?",
                (dom, row["id"])).fetchone()
            if dom and not taken:
                conn.execute(
                    "UPDATE companies SET domain = COALESCE(domain, ?) "
                    "WHERE id = ?", (dom, row["id"]))
        out.append((row["name"], url))
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m radar.domains", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    util.add_common_args(parser, as_of=False)
    args = parser.parse_args(argv)

    if args.fixtures:
        # Live-only: fixture runs resolve websites from the enrichment
        # fixtures at sieve time, so there is nothing to do here.
        print("domains: nothing to do in fixture mode")
        return 0

    conn = db.connect(args.db)
    db.init_db(conn)
    results = resolve_discovered(conn)
    conn.commit()

    found = [r for r in results if r[1]]
    print("domains: resolved %d of %d discovered company(ies) without a site"
          % (len(found), len(results)))
    for name, url in results:
        print("  %-28s %s"
              % (name[:28], url or "(unresolved; add a website_override)"))
    if results:
        print("Next: python -m radar.sieve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
