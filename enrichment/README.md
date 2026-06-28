# Curated enrichment overrides

One JSON file per company, named by its Companies House number
(`<company_number>.json`). The enrich stage reads these in every mode (not
just `--fixtures`), modeled on the `website_overrides` and `ats_overrides`
keys in `sources.yaml`. A value here wins over both the recorded test
fixtures and the auto-derived fallback (homepage meta, press regex).

Use this to feed verified, sourced facts into a live `python -m radar.enrich`
run: a rewritten one-liner, a bucketed headcount with its source, and
founders' names with public-record backgrounds.

## Rules

- Public facts only. No emails, no phone numbers, no personal contact data
  of any kind, ever. The founders entries carry a name, a public role, and a
  one-line public background only.
- `headcount_estimate` is one of the schema buckets: `1-10`, `11-25`,
  `26-50`, `51-100`, `unknown`.
- `headcount_source` names where the figure came from, honestly. When it is
  derived from Clay (which aggregates LinkedIn data), say so, for example
  `"Clay (LinkedIn-derived), 2026-06-29"`, so the provenance shows in the
  issue and the public dataset.
- Amount and stage are not set here; those live on the funding event and
  prefer press figures. Do not restate or guess them.
- Re-fetch the live company source before writing anything here; never trust
  a search snippet.

## Schema

```json
{
  "_note": "Curated live-mode enrichment. Public facts only; no contact data.",
  "company_number": "15396489",
  "one_liner": "Plain one-sentence description, rewritten from the company site.",
  "one_liner_source": "company site (verified 2026-06-29)",
  "headcount_estimate": "11-25",
  "headcount_source": "Clay (LinkedIn-derived), 2026-06-29",
  "founders": [
    {
      "name": "Jane Doe",
      "role": "CEO",
      "background": "ex-Palantir; public profile",
      "source_url": "https://example.com/about"
    }
  ],
  "ats": {"provider": "greenhouse", "token": "exampleco"}
}
```

Every key is optional. Set only what you have verified; the pipeline fills
the rest from its own best-effort sources. See
`reports/enrichment-routine-prompt.md` for the routine that writes these.
