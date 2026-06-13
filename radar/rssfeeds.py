"""Funding press via RSS: live feeds from sources.yaml, or recorded fixtures.

RSS is used to corroborate Companies House filings and to catch raises
that file late. Items become candidates when they use funding language
and a company name can be extracted from the headline; the four gates in
the sieve do the real filtering, so triage here is deliberately loose.
"""

import re
import socket
import time

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
_NAME_FROM_TITLE = re.compile(
    r"^(?P<name>.+?)\s+(?:raises?|raised|secures?|secured|lands?|landed|"
    r"closes?|closed|banks?|nets)\b",
    re.IGNORECASE,
)


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
        items.append({
            "company_name": m.group("name").strip(),
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


def load_from_dir(directory):
    """Triage saved feed files (*.xml) in a directory through the same logic
    as live feeds. Used by fixtures and by the cloud scout, which saves the
    feeds it fetches via WebFetch (a non-blocked egress) and parses them here."""
    items = []
    for path in sorted(directory.glob("*.xml")):
        parsed = feedparser.parse(str(path))
        source_name = parsed.feed.get("title", path.stem)
        items.extend(_entries_to_items(parsed.entries, source_name))
    return items


def load_fixtures():
    return load_from_dir(config.FIXTURES_DIR / "rss")
