"""Accelerator and investor portfolio mapping, for human review only.

Fetches the public portfolio pages listed in sources.yaml (accelerators:),
extracts candidate company names and links, and writes a reviewable list to
reports/accelerators/<date>.md. It does NOT touch the database and does NOT
inject leads: per the project rule, accelerator coverage is candidate
mapping for human review, never batch auto-resolve. Most portfolio companies
are historical and would drop on recency anyway, so you skim the list and
copy any recent, relevant UK companies into the leads list in sources.yaml.

  python -m radar.accelerators

The optional --resolve pass adds a step: it searches Companies House for
each candidate and writes reports/accelerators/proposed-watchlist-<date>.md,
a human approval sheet. It still touches no database and never edits
sources.yaml. A number is captured only on an exact register-name match, and
even then it is only a proposal: same-name collisions attach the wrong
London entity (the TurnUp lesson), so a human confirms the entity by its
registered office before copying the number into watchlist_company_numbers.

  python -m radar.accelerators --resolve
"""

import argparse
import datetime
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from radar import ch, config, db, rssfeeds

_ANCHOR = re.compile(
    r"<a\b[^>]*\bhref=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
    re.IGNORECASE | re.DOTALL)
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

# Navigation/social/boilerplate anchor text that is never a company name.
_STOP = {
    "home", "about", "about us", "team", "careers", "career", "contact",
    "contact us", "privacy", "privacy policy", "terms", "cookie policy",
    "cookies", "blog", "news", "insights", "login", "log in", "sign in",
    "sign up", "portfolio", "companies", "our companies", "apply",
    "apply now", "menu", "more", "read more", "learn more", "twitter", "x",
    "linkedin", "instagram", "facebook", "youtube", "github", "medium",
    "newsletter", "events", "jobs", "press", "faq", "resources", "people",
    "founders", "investors", "stories", "podcast", "subscribe", "all",
    "view all", "back", "next", "previous", "home page",
}


def fetch_html(url, timeout=15):
    try:
        resp = requests.get(url, timeout=timeout,
                            headers={"User-Agent": rssfeeds.USER_AGENT})
        return resp.text if resp.status_code == 200 else None
    except Exception:
        return None


def extract_candidates(html, base_url=""):
    """Best-effort (name, link) pairs from portfolio-page anchors. Output is
    human-reviewed, so over-inclusion is fine; obvious nav/social is filtered."""
    seen = {}
    for href, inner in _ANCHOR.findall(html or ""):
        if re.match(r"\s*(mailto:|tel:|javascript:|#)", href, re.IGNORECASE):
            continue
        name = _WS.sub(" ", _TAGS.sub(" ", inner)).strip()
        low = name.lower()
        if not name or "@" in name or low.startswith("http"):
            continue
        if low in _STOP or len(name) > 60 or len(name.split()) > 6:
            continue
        if not re.search(r"[A-Za-z]", name):
            continue
        if low not in seen:
            seen[low] = (name, urljoin(base_url, href) if base_url else href)
    return list(seen.values())


def map_accelerators(accelerators, fetch=None):
    fetch = fetch or fetch_html
    out = []
    for acc in accelerators:
        url = acc.get("url")
        html = fetch(url) if url else None
        out.append({"name": acc.get("name", url), "url": url,
                    "ok": html is not None,
                    "companies": extract_candidates(html, url) if html else []})
    return out


def write_report(root, mapping, today=None):
    today = today or datetime.date.today().isoformat()
    out_dir = Path(root) / "reports" / "accelerators"
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Accelerator portfolio candidates: %s" % today, "",
        "Review only: not verified against Companies House, not in the",
        "pipeline. Most are historical and will drop on recency; copy any",
        "recent UK companies into the leads list in sources.yaml.", "",
    ]
    for acc in mapping:
        lines.append("## %s (%s)" % (acc["name"], acc["url"]))
        if not acc["ok"]:
            lines.append("- (could not fetch the page)")
        elif not acc["companies"]:
            lines.append("- (no candidates extracted; check the page layout)")
        else:
            for name, link in acc["companies"]:
                lines.append("- %s: %s" % (name, link))
        lines.append("")
    path = out_dir / ("%s.md" % today)
    path.write_text("\n".join(lines))
    return str(path.relative_to(Path(root)))


# Anchor text that is a place, a sector tag, or site furniture, never a
# portfolio company. extract_candidates is deliberately permissive for the
# human review report; the resolve path needs precision, because a generic
# word exact-matches an unrelated UK company ("London" -> LONDON LIMITED,
# "Insurance" -> INSURANCE LTD) and wastes a human confirmation. Entries are
# stored normalized (db.normalize_name), so "News & Views" -> "news views".
_NOT_A_COMPANY = {
    # places
    "london", "paris", "berlin", "tokyo", "toronto", "japan", "india",
    "france", "vietnam", "netherlands", "menap", "singapore", "new york",
    "amsterdam", "stockholm", "munich", "dubai", "bangalore", "tel aviv",
    "germany", "spain", "europe", "americas", "asia",
    # sectors
    "insurance", "logistics", "climate", "food", "hr", "pharmaceuticals",
    "enterprise services", "sustainability", "fintech", "healthcare",
    "energy", "retail", "manufacturing", "biotech", "deeptech", "saas",
    "consumer", "marketplace", "hardware", "robotics", "gaming", "edtech",
    # site furniture missed by _STOP
    "our team", "news views", "complaints", "start", "menu",
}
_SOCIAL_HOST = re.compile(
    r"(^|\.)(linkedin|twitter|x|facebook|instagram|youtube|github|medium|"
    r"substack)\.com$", re.IGNORECASE)
_NAV_PATH = re.compile(
    r"^/?(our-team|team|about|views|complaints|location|locations|industry|"
    r"industries|sector|sectors|sustainability|apply|welcome|contact|privacy|"
    r"terms|careers|jobs|blog|news|people|press|faq|resources|events|podcast|"
    r"stories|insights)(/|$)", re.IGNORECASE)


def _resolvable(name, link):
    """True when a candidate could plausibly be a portfolio company worth
    searching Companies House for. Filters an accelerator's own nav, a
    location or sector tag, and social/profile links, each of which can
    exact-match an unrelated UK company in the resolve step."""
    norm = db.normalize_name(name)
    if not norm or norm in _NOT_A_COMPANY:
        return False
    if name.strip().startswith("["):
        return False
    parsed = urlparse(link or "")
    if _SOCIAL_HOST.search(parsed.netloc or ""):
        return False
    path = parsed.path or ""
    if path in ("", "/") or _NAV_PATH.match(path):
        return False
    return True


def _unique_candidates(mapping):
    """Flatten the per-accelerator (name, link) pairs, filtered to plausible
    companies and deduped by normalized name, so a company listed by two
    accelerators is searched once and nav/boilerplate is never searched."""
    out = []
    seen = set()
    for acc in mapping:
        for name, link in acc["companies"]:
            if not _resolvable(name, link):
                continue
            key = db.normalize_name(name)
            if key and key not in seen:
                seen.add(key)
                out.append((name, link))
    return out


def resolve_to_numbers(candidates, client):
    """For each (name, link), search Companies House and keep a number ONLY
    on an exact normalize_name match against a hit's title.

    Returns dicts {name, link, company_number, register_name, office,
    confidence}. confidence is 'exact-name' (one exact match, number and
    office captured), 'ambiguous' (several share the normalized name, number
    None), or 'unresolved' (no exact match or the search failed, number
    None). Never a guess: anything but a single exact match leaves
    company_number None for the human to resolve by hand."""
    resolved = []
    for name, link in candidates:
        norm = db.normalize_name(name)
        row = {"name": name, "link": link, "company_number": None,
               "register_name": None, "office": None, "confidence": "unresolved"}
        try:
            hits = client.search_companies(name)
        except Exception as exc:
            print("  warn: search for %r failed: %s" % (name, exc))
            resolved.append(row)
            continue
        exact = [h for h in hits
                 if db.normalize_name(h.get("title", "")) == norm]
        if len(exact) == 1:
            hit = exact[0]
            row["confidence"] = "exact-name"
            row["company_number"] = hit.get("company_number")
            row["register_name"] = hit.get("title")
            try:
                row["office"] = ch.registered_office_text(
                    client.get_profile(hit["company_number"]))
            except Exception:
                row["office"] = hit.get("address_snippet")
        elif len(exact) > 1:
            row["confidence"] = "ambiguous"
        resolved.append(row)
    return resolved


def write_proposed_watchlist(root, resolved, today=None):
    """Write reports/accelerators/proposed-watchlist-<date>.md: a human
    approval sheet, deliberately not machine-ingested. Exact-name rows show
    the register name and registered office so the human confirms the entity
    (the TurnUp check) before copying the number into
    watchlist_company_numbers in sources.yaml. Writes no DB rows and never
    edits sources.yaml. Returns the relative path."""
    today = today or datetime.date.today().isoformat()
    out_dir = Path(root) / "reports" / "accelerators"
    out_dir.mkdir(parents=True, exist_ok=True)
    exact = [r for r in resolved if r["confidence"] == "exact-name"]
    ambiguous = [r for r in resolved if r["confidence"] == "ambiguous"]
    unresolved = [r for r in resolved if r["confidence"] == "unresolved"]
    lines = [
        "# Proposed Companies House watchlist: %s" % today, "",
        "Resolved from accelerator portfolios for review. NOTHING here is",
        "added automatically. Same-name collisions attach the wrong London",
        "entity (the TurnUp lesson), so confirm each by its register name and",
        "registered office before copying its number into",
        "watchlist_company_numbers in sources.yaml.", "",
        "## Confirm before adding (exact-name match)", "",
    ]
    if exact:
        for r in exact:
            lines.append("- %s -> %s (%s, %s) [%s]" % (
                r["name"], r["company_number"], r["register_name"],
                r["office"] or "office unknown", r["link"]))
    else:
        lines.append("- (none)")
    lines += ["", "## Ambiguous (pick by hand)", ""]
    if ambiguous:
        for r in ambiguous:
            lines.append("- %s: several companies share this name; pick the "
                         "right entity on Companies House. [%s]"
                         % (r["name"], r["link"]))
    else:
        lines.append("- (none)")
    lines += ["", "## Unresolved (no exact match)", ""]
    if unresolved:
        for r in unresolved:
            lines.append("- %s [%s]" % (r["name"], r["link"]))
    else:
        lines.append("- (none)")
    lines.append("")
    path = out_dir / ("proposed-watchlist-%s.md" % today)
    path.write_text("\n".join(lines))
    return str(path.relative_to(Path(root)))


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m radar.accelerators", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--resolve", action="store_true",
        help="also search Companies House for each candidate and write a "
             "proposed-watchlist approval sheet (needs the CH API key)")
    args = parser.parse_args(argv)

    accelerators = config.load_sources().get("accelerators") or []
    if not accelerators:
        print("accelerators: none configured (add an accelerators: list to "
              "sources.yaml).")
        return 0

    if args.resolve:
        # Check the key before fetching any page: without it there is nothing
        # to resolve against, so fail fast.
        key = config.companies_house_key()
        if not key:
            print("accelerators --resolve: needs COMPANIES_HOUSE_API_KEY in "
                  ".env. Run 'python -m radar.todo list' for the setup "
                  "checklist, or run without --resolve for the review report.")
            return 2
        mapping = map_accelerators(accelerators)
        candidates = _unique_candidates(mapping)
        print("Resolving %d candidate(s) against Companies House ..."
              % len(candidates))
        resolved = resolve_to_numbers(candidates, ch.CompaniesHouseClient(key))
        path = write_proposed_watchlist(config.ROOT, resolved)
        exact = sum(1 for r in resolved if r["confidence"] == "exact-name")
        print("accelerators --resolve: wrote %s" % path)
        print("  %d exact-name match(es) to confirm, %d total candidate(s)."
              % (exact, len(resolved)))
        print("  Confirm each entity by its registered office, then copy its "
              "number into sources.yaml watchlist_company_numbers.")
        print("  No database was touched and sources.yaml was not edited.")
        return 0

    mapping = map_accelerators(accelerators)
    path = write_report(config.ROOT, mapping)
    total = sum(len(acc["companies"]) for acc in mapping)
    print("accelerators: wrote %s" % path)
    print("  %d candidate companies across %d source(s), for review only."
          % (total, len(mapping)))
    print("  Copy recent UK companies into sources.yaml leads:.")
    print("  No database was touched and nothing was verified; the pipeline "
          "does that.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
