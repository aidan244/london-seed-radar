"""Lead sources beyond the RSS feeds: the cloud scouts' UK shortlists
and a human-curated leads list in sources.yaml.

Each lead becomes a press item in the exact shape radar.rssfeeds produces,
so radar.ingest resolves it against Companies House and the four gates
verify it locally. Leads are candidates, never facts: nothing here bypasses
a gate, fabricates a UK marker, or features anything. A lead that does
not resolve to a UK company, has no live site, or falls outside the
window is dropped by the sieve like any other candidate.
"""

import csv
import datetime
import io
import re
from pathlib import Path

from radar import config, db, stages

# Human date spellings a scout or predraft prose line may use. The recency
# gate (and ingest's find_or_create_event) require an ISO date, exactly as
# rssfeeds emits; a lead carrying "17 June 2026" or "approx. 10 June 2026
# (featured in the UKTN roundup)" must be normalised here or it crashes
# ingest. Anything we cannot parse to a real date drops to None, and a lead
# with no usable date is filtered out like any other dateless lead.
_HUMAN_DATE_FORMATS = ("%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y")
_DATE_IN_PROSE = re.compile(
    r"\d{4}-\d{2}-\d{2}"                       # ISO, e.g. 2026-06-17
    r"|\d{1,2}\s+[A-Za-z]{3,}\s+\d{4}"         # 17 June 2026
    r"|[A-Za-z]{3,}\s+\d{1,2},?\s+\d{4}")      # June 17, 2026


def _iso_date(value):
    """Normalise a lead's date string to ISO 'YYYY-MM-DD', or None.

    Accepts an already-ISO date, common human spellings, and prose that
    embeds a date ('approx. 10 June 2026 (featured in ...)'). Returns None
    when no real date can be recovered, so the lead is dropped, never
    passed on to crash ingest."""
    if not value:
        return None
    text = str(value).strip()
    m = _DATE_IN_PROSE.search(text)
    if not m:
        return None
    found = m.group(0).replace(",", "")
    try:
        return datetime.date.fromisoformat(found).isoformat()
    except ValueError:
        pass
    for fmt in _HUMAN_DATE_FORMATS:
        try:
            return datetime.datetime.strptime(found, fmt).date().isoformat()
        except ValueError:
            continue
    return None

# The scouts emit a stable machine-readable block alongside the prose:
#   ```radar-leads (csv)
#   name,stage,amount_gbp,date,url,source
#   RevEng.AI,series-a,,2026-05-27,https://...,SecurityWeek
#   ```
_SCOUT_BLOCK = re.compile(r"```radar-leads[^\n]*\n(.*?)```", re.DOTALL | re.IGNORECASE)

# Canonical stage spellings the machine block may use; anything else falls
# through to stages.detect_stage (which reads prose like "Series A").
_CANON_STAGE = {
    "pre-seed": "pre-seed", "preseed": "pre-seed", "pre seed": "pre-seed",
    "seed": "seed", "series-a": "series-a", "series a": "series-a",
    "seriesa": "series-a",
}


def _stage(text):
    if not text:
        return None
    key = text.strip().lower()
    if key in _CANON_STAGE:
        return _CANON_STAGE[key]
    return stages.detect_stage(text)


def _amount(text):
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    if re.fullmatch(r"\d+", s):          # plain pounds in the machine block
        return int(s)
    return stages.parse_amount_gbp(s)    # prose like "£1.5m"; non-GBP -> None


def _item(name, stage_text, amount_text, date, url, source, company_number=None):
    """Build one press-shaped item, or None when there is no usable name.

    company_number, when a lead supplies one, is a human-verified Companies
    House number for the exact entity (often a brand whose registered name
    differs: Conduct -> CONDUCT AI LTD). ingest resolves the press item
    straight to that profile instead of a naive name search, which is how
    same-name collisions get the wrong London office (the TurnUp lesson)."""
    name = re.sub(r"[*`\[\]]", "", (name or "")).strip()
    if not name:
        return None
    src = (source or "scout").strip() or "scout"
    number = str(company_number).strip() if company_number else None
    return {
        "company_name": name,
        "title": "%s funding lead" % name,
        "summary": "Lead surfaced by %s; stage %s. Verify locally before "
                   "featuring." % (src, stage_text or "unknown"),
        "url": (url or "").strip() or None,
        "published_date": _iso_date(date),
        "source_name": "%s (lead)" % src,
        "stage": _stage(stage_text),
        "amount_gbp": _amount(amount_text),
        "company_number": number or None,
    }


def parse_scout_report(text):
    """Items from one scout/predraft report: the machine block if present,
    else a best-effort parse of the prose shortlist."""
    m = _SCOUT_BLOCK.search(text or "")
    if m:
        return _parse_block(m.group(1))
    return _parse_prose(text or "")


def _parse_block(block_text):
    items = []
    for row in csv.DictReader(io.StringIO(block_text.strip())):
        item = _item(row.get("name"), row.get("stage"), row.get("amount_gbp"),
                     row.get("date"), row.get("url"), row.get("source"),
                     row.get("company_number"))
        if item:
            items.append(item)
    return items


def _field(block, label):
    m = re.search(r"\*\*%s:?\*\*\s*(.+)" % re.escape(label), block, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _parse_prose(text):
    """Fallback for reports written before the machine block existed. Splits
    on '### N. Name' headings and reads the labelled fields under each."""
    items = []
    for part in re.split(r"(?m)^###\s+", text)[1:]:
        head, _, body = part.partition("\n")
        name = re.sub(r"^\d+\.\s*", "", head)
        stage = _field(body, "Detected stage") or _field(body, "Stage")
        date = _field(body, "Published date") or _field(body, "Date")
        amount = _field(body, "Parsed amount (GBP)") or _field(body, "Amount")
        url_field = _field(body, "URL") or _field(body, "Source") or ""
        mu = re.search(r"https?://\S+", url_field)
        url = mu.group(0).rstrip(").,") if mu else None
        source = _field(body, "Source")
        if source:
            source = re.sub(r"https?://\S+", "", source).strip(" ,") or "scout"
        item = _item(name, stage, amount, date, url, source or "scout")
        if item:
            items.append(item)
    return items


def load_scout_leads(root=None):
    """Parse every reports/scout/*.md and reports/predraft/*.md on disk.

    Only leads with a published date survive: a date is what the recency
    gate needs, and dropping the rest keeps heading-only noise (dropped or
    borderline mentions the report lists without a date) out of the pool."""
    root = Path(root or config.ROOT)
    items = []
    for sub in ("scout", "predraft"):
        directory = root / "reports" / sub
        if directory.is_dir():
            for path in sorted(directory.glob("*.md")):
                # One unreadable or badly-encoded cloud-written report must
                # not abort the whole ingest; skip it, say so, keep going.
                try:
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    print("  warn: skipping unreadable scout report %s: %s"
                          % (path.name, exc))
                    continue
                items.extend(parse_scout_report(text))
    return _dedup([item for item in items if item.get("published_date")])


def load_manual_leads(sources=None):
    """Human-curated leads from sources.yaml: a list of
    {name, stage, url, date, amount_gbp?, source?}."""
    sources = sources if sources is not None else config.load_sources()
    out = []
    for lead in (sources.get("leads") or []):
        item = _item(lead.get("name"), lead.get("stage"),
                     lead.get("amount_gbp"), lead.get("date"),
                     lead.get("url"), lead.get("source") or "manual lead",
                     lead.get("company_number"))
        if item and item["published_date"]:   # a date is required for recency
            out.append(item)
    return out


def load_leads(root=None, sources=None):
    """All lead items (scout reports plus manual leads), deduped by name."""
    return _dedup(load_scout_leads(root) + load_manual_leads(sources))


# Richer fields a sparser duplicate must never discard from the kept item:
# a human-verified company_number, the source URL, and the amount. A scout
# entry with the freshest date but no URL would otherwise drop the manual
# lead's link, leaving a broken "[source](None)" in the draft.
_STICKY_FIELDS = ("company_number", "url", "amount_gbp")


def _merge_sticky(keep, other):
    for field in _STICKY_FIELDS:
        if not keep.get(field) and other.get(field):
            keep[field] = other[field]
    return keep


def _dedup(items):
    """Keep one item per normalized company name, preferring the most recent
    published_date so a later scout run supersedes an earlier one, but never
    losing a verified company_number, URL, or amount that any duplicate
    carries."""
    best = {}
    for item in items:
        key = db.normalize_name(item["company_name"])
        current = best.get(key)
        if current is None:
            best[key] = dict(item)
        elif (item.get("published_date") or "") > (
                current.get("published_date") or ""):
            best[key] = _merge_sticky(dict(item), current)
        else:
            _merge_sticky(current, item)
    return list(best.values())
