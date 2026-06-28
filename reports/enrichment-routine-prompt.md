# Enrichment routine prompt (source of truth)

This is an interactive, on-demand routine run locally by Claude with the
Clay and WebSearch tools available. It does not run in the cloud scout
routines, which carry no MCP connectors by rule. It writes curated
enrichment files; the deterministic pipeline consumes them on the next
`python -m radar.enrich`.

Why this exists: in live mode the enrich stage has only weak sources. The
one-liner is the raw homepage meta tag, founders come from a "founded by
X and Y" regex, and headcount is almost always "unknown". This routine
uses Clay and WebSearch to write verified, sourced facts into
`enrichment/<company_number>.json`, which the enrich stage reads in every
mode and prefers over its auto-derived fallback.

## Hard rules for the routine (keep them in mind)

- Public facts only. No emails, no phone numbers, no personal contact
  data, ever. Founders carry a name, a public role, and a one-line public
  background only. The founders table has no contact columns; do not add
  any data that would imply one.
- Clay contact tools are forbidden: never call `find-and-enrich-contacts*`
  or `add-contact-data-points`. Company-level enrichment only.
- Re-fetch the live source before writing. Never trust a search snippet or
  a cached value; open the company site or the cited article.
- Never overwrite a press funding figure and never convert a currency.
  Amount and stage live on the funding event and prefer press; this file
  does not set them.
- Produce files only. Do not send, post, publish, or touch the database.
- No em dashes anywhere.

## Which companies to enrich

Run after sieve, against the local database:

```
python -c "import sqlite3; c=sqlite3.connect('radar.db'); c.row_factory=sqlite3.Row; \
print('\n'.join('%s\t%s\t%s' % (r['company_number'], r['name'], r['website'] or '') \
for r in c.execute(\"SELECT c.company_number, c.name, c.website FROM funding_events fe \
JOIN companies c ON c.id=fe.company_id WHERE fe.status='sieved' AND c.company_number IS NOT NULL\")))"
```

Each row is a sieved company with a Companies House number. Enrich each.

## Per-company steps

1. Resolve the domain from the company's `website` (or the live site you
   confirm). Clay needs a domain or a LinkedIn company URL, never a bare
   name.

2. Clay `find-and-enrich-company` by domain, requesting only the data
   points you will use:
   - Headcount Growth, to choose a bucket (`1-10`, `11-25`, `26-50`,
     `51-100`). If Clay cannot place it, leave headcount out and let the
     pipeline keep "unknown".
   - Latest Funding, to cross-check the stage and amount already on the
     event. If Clay disagrees with the press figure, note it for the human;
     do not change the event and do not write an amount here.
   - Open Jobs, to corroborate the ATS find (optional).
   - Recent News, for context only (optional).
   Do not add data points the company does not need; enrichments cost
   credits.

3. WebSearch plus a live fetch for the parts Clay does not cover well:
   - A clean one-liner, rewritten in plain words from the live company
     site (not the meta tag, not a press snippet verbatim).
   - Founders' names, public roles, and one-line public-record backgrounds,
     from the company site or a credible article. Record the `source_url`.

4. Write `enrichment/<company_number>.json` following the schema in
   `enrichment/README.md`. Set only fields you verified. For a
   Clay-derived headcount, set
   `"headcount_source": "Clay (LinkedIn-derived), <today>"` so the
   provenance is visible in the issue and the public dataset. For a
   site-derived one-liner, use
   `"one_liner_source": "company site (verified <today>)"`.

## After the routine

Run `python -m radar.enrich` (live). The curated values land on the
company row, replacing the weak fallbacks. Spot-check one row to confirm
the one-liner reads cleanly, the headcount bucket and its honest source
are set, and founders were inserted. Commit the new `enrichment/*.json`
files (public facts only, safe for the public repo).
