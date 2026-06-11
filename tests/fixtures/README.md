# Recorded fixtures

Everything in this directory is sample data so the full pipeline runs
end-to-end with no API key and no network: `python -m radar.demo`.

All companies, people, websites, and press items here are fictional.
The JSON shapes mirror the real APIs exactly:

- `companies_house/`: company profiles and capital filing histories in
  the Companies House REST API shape. SH01 items are the funding trigger.
- `rss/`: RSS 2.0 feeds in the shape feedparser sees from real funding
  press. Includes deliberate drop cases: Ukraine (the "uk" word-boundary
  trap), New England (the "england" trap), a Series B, a stale event,
  and a stealth company with no live website.
- `ats/`: Greenhouse, Ashby, and Lever job-board JSON.
  `ashby_tansymoney.json` records a 404: the org disabled the public
  posting API, so hiring is unverifiable.
- `enrichment/`: recorded results of the enrich step (company site and
  press only), keyed by company number. No personal contact data.

Fixture dates are fixed in early June 2026; the demo always runs as of
2026-06-10 so it stays reproducible.
