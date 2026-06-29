# Cloud scout routine prompt (source of truth)

This is the discovery logic for the two scheduled cloud routines at
claude.ai/code/routines. They run in Anthropic's cloud on a fresh
checkout with no Companies House key and no database, so they are
press-triage scouts only; the authoritative pipeline runs locally.

Why this exists: the cloud sandbox IP is blocked by the feed providers.
Every feed returns HTTP 403 from the sandbox and from the WebFetch tool
alike (confirmed 2026-06-12 and 2026-06-13). So the routines fetch feeds
through a public proxy (config in sources.yaml, see feed_proxy) and also
run a WebSearch pass; either leg alone can carry the report.

How to use: paste the Discovery block below into both routines' prompts,
replacing the current feed-fetch instructions. The only per-routine
difference is the output path and the Sunday merge step, both noted.
Both routines need WebSearch and WebFetch in their allowed_tools, or the
WebSearch leg silently cannot run; add them when editing. After editing,
re-check that no MCP connectors are attached (the API has auto-attached
Gmail and others before; strip them, no-send rule).

## Hard rules for the routine (keep in the prompt)

- Never send, post, publish, or message anyone. Produce files only.
- Never push to main. Deliver a branch and a PR.
- No MCP connectors attached. Public pages and public APIs only.
- Nothing here is verified against Companies House; say so in the report.
  Featuring and CH verification happen later in the local pipeline.

## Discovery block (paste into both routines)

Discover this week's London pre-seed, seed, and Series A raises two ways
and merge them. The lookback window is lookback_days in sources.yaml.

1. Feeds via proxy.
   a. List the proxied feeds:
      `python -c "import json; from radar import rssfeeds; print(json.dumps(rssfeeds.proxied_feeds()))"`
   b. `mkdir -p /tmp/radar-feeds`. For each entry, WebFetch its
      proxied_url and save the RAW response body to
      `/tmp/radar-feeds/<name>.xml` (slugify the name). Do not summarise;
      load_from_dir needs the raw XML.
   c. Parse what saved:
      `python -c "import json, pathlib; from radar import rssfeeds; print(json.dumps(rssfeeds.load_from_dir(pathlib.Path('/tmp/radar-feeds'))))"`
   d. If a feed's saved file is not valid XML (the proxy failed, or
      WebFetch returned prose), record it as failed for that feed and let
      the WebSearch leg cover it. Do not invent entries.

2. WebSearch pass (always run, even if feeds worked).
   Search for recently funded London startups in the window, for example
   "London startup raises seed", "London Series A funding", "London
   pre-seed round", each scoped to the current month. For each credible
   hit capture company, stage, amount if stated, date, and the source
   URL. Treat these as leads, not facts: never feature from a snippet.

3. Merge and gate. Dedup by company name across both legs. Keep only
   London pre-seed/seed/Series A raises inside the lookback window. Drop
   the rest with a one-line reason each.

## Report format

Write a markdown report with, in order:

- A per-feed status table: feed name, proxy result (XML parsed or
  failed), entry count, funding items found. This is how we see whether
  the proxy worked from the cloud this run.
- The shortlist: company, stage, amount or "undisclosed", date, source
  URL, and which leg found it (feed or websearch).
- A machine-readable shortlist block (see below), so the local pipeline
  can ingest the leads deterministically.
- Dropped candidates with reasons.
- A line stating nothing is CH-verified; the local pipeline does that.

### Machine-readable shortlist block (required)

Immediately after the prose shortlist, emit the same companies as a
fenced CSV block exactly like this (the local radar.leads parser reads
it):

```radar-leads (csv)
name,stage,amount_gbp,date,url,source
RevEng.AI,series-a,,2026-05-27,https://www.example.com/article,SecurityWeek
Acme Bio,seed,1500000,2026-06-02,https://www.example.com/acme,UKTN
```

Rules for the block:
- One row per shortlisted company, header line exactly as shown.
- stage is one of pre-seed, seed, series-a (lowercase, hyphenated).
- amount_gbp is the round size in whole pounds, or blank if the figure
  is not in GBP or is undisclosed. Never convert a currency; leave it
  blank rather than guess.
- date is the YYYY-MM-DD the round was announced.
- url is the single best public source link; source is the outlet name.
- Include only companies in the shortlist (London, in-scope stage, in
  window). The local pipeline still re-verifies every row.

Output path:
- Radar scout (Tue/Fri): `reports/scout/<date>.md`.
- Radar Sunday pre-draft: `reports/predraft/<date>.md`. First also read
  the week's `reports/scout/*.md`, fold their shortlists into the merge,
  and append the existing Sunday checklist at the bottom.

Deliver the report on a new branch as a PR. Never push to main.
