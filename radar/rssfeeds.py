"""Funding press via RSS: live feeds from sources.yaml, or recorded fixtures.

RSS is used to corroborate Companies House filings and to catch raises
that file late. Items become candidates when they use funding language
and a company name can be extracted from the headline; the four gates in
the sieve do the real filtering, so triage here is deliberately loose.
"""

import re
import socket
import time
import urllib.parse

import feedparser

from radar import config, stages

# Browser-like UA plus a project pointer. Local testing shows these feeds
# return 200 even to a bot UA, so this is not the fix for the cloud
# sandbox's IP-based 403s; it is hygiene against feeds that filter on UA.
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 "
              "Safari/537.36 (+https://github.com/aidan244/london-seed-radar)")
REQUEST_HEADERS = {"Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8"}
FEED_TIMEOUT = 15

# "Acme Labs raises £2m seed round ..." -> "Acme Labs"
# Keep the verb list in sync with stages.FUNDING_WORDS (minus the bare
# nouns, which never follow a company name this way).
_NAME_FROM_TITLE = re.compile(
    r"^(?P<name>.+?)\s+(?:raises?|raised|secures?|secured|lands?|landed|"
    r"closes?|closed|banks?|nets|bags?|bagged|scoops?|scooped|"
    r"pockets?|pocketed|grabs?|grabbed|snags?|snagged)\b",
    re.IGNORECASE,
)

# Editorial lead-ins that are not part of a company name.
_NAME_PREFIX = re.compile(
    r"^(?:exclusive|breaking|report|revealed|watch|meet the|meet)[:,]?\s+",
    re.IGNORECASE)
# A name ending in a grammar word is a truncated headline fragment, not a
# company ("UK fintech's stablecoin clash with the").
_TRAILING_STOPWORD = re.compile(
    r"\b(?:the|a|an|and|to|of|with|for|in|on|it|its|his|her|their|is|are|"
    r"has|have|comes|as|at|by)$", re.IGNORECASE)


def _plausible_company_name(name):
    """False for headline fragments masquerading as company names. The
    live DB accumulated rows like 'VivaTech: A Record 10th Edition Comes
    to a' because everything before a funding verb was taken as the name;
    those rows re-seed themselves on every ingest. Deliberately loose:
    real companies with odd names must still pass, and the four gates
    remain the actual filter."""
    name = (name or "").strip()
    if not name or len(name) > 60 or len(name.split()) > 6:
        return False
    if ":" in name:
        return False
    if _TRAILING_STOPWORD.search(name):
        return False
    return True


def _entry_date(entry):
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return time.strftime("%Y-%m-%d", parsed)
    return None


def _entries_to_items(entries, source_name):
    items = []
    for entry in entries:
        title = entry.get("title", "")
        summary = re.sub(r"<[^>]+>", " ", entry.get("summary", ""))
        text = "%s %s" % (title, summary)
        if not stages.mentions_funding(text):
            continue
        m = _NAME_FROM_TITLE.match(title)
        if not m:
            continue
        name = _NAME_PREFIX.sub("", m.group("name").strip()).strip()
        if not _plausible_company_name(name):
            continue
        items.append({
            "company_name": name,
            "title": title,
            "summary": summary.strip(),
            "url": entry.get("link"),
            "published_date": _entry_date(entry),
            "source_name": source_name,
            "stage": stages.detect_stage(text),
            "amount_gbp": stages.parse_amount_gbp(text),
        })
    return items


def _fetch_one(url):
    """Fetch and parse a single feed, with one retry on a transient error.
    Returns the feedparser result. Network timeouts are bounded by the
    socket default we set around the call."""
    last = None
    for _ in range(2):
        parsed = feedparser.parse(url, agent=USER_AGENT,
                                  request_headers=dict(REQUEST_HEADERS))
        status = parsed.get("status")
        # A clean 200 (or a file:// read, which has no status) is done.
        if status is None or status == 200:
            return parsed
        last = parsed
        # Only retry server-side hiccups; a 403/404 will not change.
        if status not in (429, 500, 502, 503, 504):
            return parsed
        time.sleep(1)
    return last


def fetch_live():
    """Fetch every configured feed live. Returns both the triaged items and
    a per-feed status record, so callers can see which feeds 403'd, timed
    out, or simply carried no funding news instead of a silent empty list."""
    feeds = config.load_sources().get("rss_feeds") or []
    items = []
    feed_status = []
    previous_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(FEED_TIMEOUT)
    try:
        for feed in feeds:
            name = feed.get("name", feed["url"])
            error = None
            try:
                parsed = _fetch_one(feed["url"])
            except Exception as exc:  # network error: record, do not abort
                feed_status.append({"name": name, "url": feed["url"],
                                    "status": None, "entries": 0,
                                    "funding_items": 0, "error": str(exc)})
                continue
            if parsed.get("bozo") and not parsed.entries:
                error = str(parsed.get("bozo_exception") or "malformed feed")
            found = _entries_to_items(parsed.entries, name)
            items.extend(found)
            feed_status.append({"name": name, "url": feed["url"],
                                "status": parsed.get("status"),
                                "entries": len(parsed.entries),
                                "funding_items": len(found), "error": error})
    finally:
        socket.setdefaulttimeout(previous_timeout)
    return {"items": items, "feeds": feed_status}


def load_live():
    return fetch_live()["items"]


def proxied_feeds():
    """Feed list rewritten to go through the configured cloud-scout proxy.

    The scheduled cloud routines run from an IP the feed providers block:
    every feed returns HTTP 403 from the sandbox and from the WebFetch
    tool alike (confirmed 2026-06-12 and 2026-06-13). The routine fetches
    each entry's proxied_url instead, which requests the feed from a
    non-blocked IP and returns the raw body for load_from_dir. This is
    best-effort triage; the local pipeline fetches feeds directly and
    stays the authoritative source. Returns one record per feed with its
    name, the direct url, and the proxied_url (equal to url when no
    feed_proxy template is configured)."""
    cfg = config.load_sources()
    feeds = cfg.get("rss_feeds") or []
    template = (cfg.get("feed_proxy") or {}).get("template") or ""
    out = []
    for feed in feeds:
        url = feed["url"]
        if template:
            proxied = template.replace("{url}", urllib.parse.quote(url, safe=""))
        else:
            proxied = url
        out.append({"name": feed.get("name", url), "url": url,
                    "proxied_url": proxied})
    return out


def load_from_dir(directory):
    """Triage saved feed files (*.xml) in a directory through the same logic
    as live feeds. Used by fixtures and by the cloud scout, which saves the
    feeds it fetches through the proxy (see proxied_feeds) and parses them here."""
    items = []
    for path in sorted(directory.glob("*.xml")):
        parsed = feedparser.parse(str(path))
        source_name = parsed.feed.get("title", path.stem)
        items.extend(_entries_to_items(parsed.entries, source_name))
    return items


def load_fixtures():
    return load_from_dir(config.FIXTURES_DIR / "rss")
