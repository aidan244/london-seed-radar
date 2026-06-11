"""Funding press via RSS: live feeds from sources.yaml, or recorded fixtures.

RSS is used to corroborate Companies House filings and to catch raises
that file late. Items become candidates when they use funding language
and a company name can be extracted from the headline; the four gates in
the sieve do the real filtering, so triage here is deliberately loose.
"""

import re
import time

import feedparser

from radar import config, stages

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


def load_live():
    items = []
    feeds = config.load_sources().get("rss_feeds") or []
    for feed in feeds:
        parsed = feedparser.parse(feed["url"])
        items.extend(_entries_to_items(parsed.entries, feed.get("name", feed["url"])))
    return items


def load_fixtures():
    items = []
    fixture_dir = config.FIXTURES_DIR / "rss"
    for path in sorted(fixture_dir.glob("*.xml")):
        parsed = feedparser.parse(str(path))
        source_name = parsed.feed.get("title", path.stem)
        items.extend(_entries_to_items(parsed.entries, source_name))
    return items
