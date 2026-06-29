# Candidate verification routine prompt (source of truth)

An interactive, on-demand routine run locally by Claude with the Clay and
WebSearch tools. It confirms a candidate's real headquarters country and its
funding, so a same-name UK entity is not featured for a foreign company (the
TurnUp lesson), and writes the verdict into the curated enrichment file the
sieve already reads.

## Why this exists, and what Clay can and cannot do here

Discovery (RSS, the cloud scout's WebSearch, manual leads) surfaces company
names. Ingest then resolves each name against Companies House, and a
same-name UK company can attach a London registered office to a foreign
funding event. We saw three this window: Wayout (Stockholm), Almetra
(Berlin), and Flagright (San Francisco), each with a real London office on a
same-name UK entity.

The deterministic pipeline already vetoes the first kind: if the press
asserts a non-UK HQ ("the Swedish developer", "Berlin-based"), the geography
gate drops it (radar/geo.find_foreign_hq). This routine covers the second
kind, where the press says nothing about location (Flagright's lead was just
"Flagright funding lead"). Clay knows the HQ country, so it fills the gap.

Important scope note: Clay's MCP cannot DISCOVER companies by criteria.
There is no "find UK companies that raised seed this week" search;
find-and-enrich-company needs a domain or LinkedIn URL you already have. So
Clay is a verification and enrichment layer, not a source of new candidates.
The funnel wideners are WebSearch breadth, the accelerator watchlist
(radar.accelerators --resolve), and the Companies House SH01 path, not Clay.
If you build a Clay table/workflow for UK funding and expose it as a
subroutine, run_subroutine could pull from it; none is configured today.

## Hard rules for the routine

- Public, company-level facts only. No personal contact data, ever. Clay
  contact tools (find-and-enrich-contacts*, add-contact-data-points) are
  forbidden.
- Re-check the live source before writing. Never feature from a snippet.
- Produce files only. Do not send, post, publish, or touch the database.
- No em dashes anywhere.

## Which candidates to verify

After domains resolution and sieve, against the local database, list
candidates that have a resolvable website and a Companies House number:

```
python -c "import sqlite3; c=sqlite3.connect('radar.db'); c.row_factory=sqlite3.Row; \
print('\n'.join('%s\t%s\t%s' % (r['company_number'], r['name'], r['website'] or '') \
for r in c.execute(\"SELECT c.company_number, c.name, c.website FROM funding_events fe \
JOIN companies c ON c.id=fe.company_id WHERE fe.status IN ('discovered','sieved') \
AND c.company_number IS NOT NULL\")))"
```

Prioritise candidates whose press coverage does not state a location, since
the geography gate cannot judge those on its own.

## Per-candidate steps

1. Clay find-and-enrich-company by the company's domain (no data points
   needed; the base record carries `country`, `locality`, and `description`).
   Read the primary `country` (ISO, e.g. `GB`, `US`, `SE`, `DE`).
2. Cross-check against the live site and one press source: does the real
   company in the article match this domain and country? Watch for a generic
   name resolving to the wrong company (a "Zaro" startup vs a "Zaro" bakery).
3. Write `hq_country` into `enrichment/<company_number>.json` (create or
   merge): `"hq_country": "GB"` for a confirmed UK company, or the real ISO
   country otherwise. Keep public facts only; no contact data.

## Effect

On the next sieve, a candidate whose curated `hq_country` is set and is not
`GB` is dropped at the geography gate with a recorded reason, even if a
London office is attached. A `GB` value documents that the entity was
checked. Commit the `enrichment/*.json` files (public facts, safe for the
public repo).
