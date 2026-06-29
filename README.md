# London Seed Radar

A biweekly briefing on every newly funded pre-seed, seed, and Series A
company in the UK, London first: what they do, who founded them, a
headcount estimate, and live hiring signals from public ATS job boards,
with remote-friendly and grad-friendly roles flagged. For founders,
operators, and angels in the UK early-stage scene, and for students
hunting internships and first jobs at startups.

The pipeline produces drafts and files; a human edits, publishes, and
sends. Nothing in this repo can post or send anything. Built on public
sources only: Companies House filings, funding press RSS, and the open
JSON job-board APIs of Greenhouse, Ashby, and Lever.

## Quickstart

```bash
git clone <this repo> && cd <repo>
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in the Companies House key when you have it
python -m radar.init          # create the DB, seed the setup checklist
python -m radar.todo list     # see what only a human can do
python -m radar.demo          # offline end-to-end proof, no key needed
```

The demo ingests recorded fixtures (fictional companies), runs the
sieve, enriches, builds a draft issue in `issues/2026-06-10/`, and
publishes the static site into `docs/`. It is deterministic and safe to
re-run; it refuses to touch a database that holds live data.

## The biweekly cycle

```bash
python -m radar.ingest            # Companies House + RSS -> candidates
python -m radar.sieve --dry-run   # preview gate outcomes (drops are final)
python -m radar.sieve             # apply the four gates
python -m radar.enrich            # one-liner, founders, headcount, ATS check
python -m radar.issue             # draft issue + research briefs + issue todos
# you: edit issues/<date>/draft-issue.md, the voice must be yours
python -m radar.publish           # export dataset, regenerate docs/ site
# you: commit and push (Pages serves docs/), paste into the newsletter,
#      post, message founders, then:
python -m radar.metrics log --subscribers N --open-rate N
python -m radar.todo list         # nothing pending? this issue is done
```

`python -m radar` lists every command. `python -m radar.status` is the
one-screen overview.

## The four gates

Every candidate passes all four or is dropped with a recorded reason:

1. Geography: the UK, London first, matched on word boundaries only
   ("uk" never matches Ukraine, "england" never matches New England).
2. Stage: pre-seed, seed, or Series A.
3. Recency: inside the lookback window (default 14 days, sources.yaml).
4. Reality: a live website plus a corroborated funding event (Companies
   House filing or at least one press source).

Status flow is forward-only: discovered -> sieved -> enriched ->
featured -> published, with dropped as a terminal branch.

## Data sources and honest limits

- Companies House filing history (category capital): an SH01 form is
  the funding trigger. It proves a raise happened and when; the amount
  is usually in an attached PDF, so amounts are best-effort and press
  figures are preferred. Get a free API key at
  developer.company-information.service.gov.uk and put it in `.env`.
- Funding press RSS (sources.yaml): corroborates filings and catches
  raises that file late.
- ATS boards: Greenhouse, Ashby, Lever public JSON. Some Ashby orgs
  disable the public API; those show as "unverifiable", never guessed.
- Headcount: bucketed estimate with its source stored and shown.

Live smoke tests, once keys exist:

```bash
python -m radar.smoke companies_house --query monzo
python -m radar.smoke rss
python -m radar.smoke ats greenhouse <board-token>
```

## Tests

```bash
python -m unittest discover -s tests
```

Covers the word-boundary geography gate, stage detection, all four
sieve gates, the forward-only status guard, and DB-level dedup.

## Repository layout

```
radar/            the pipeline, one module per command
radar/templates/  jinja2 templates for briefs, the issue, and the site
tests/fixtures/   recorded API responses (fictional companies)
issues/           issue drafts and research briefs
docs/             GitHub Pages site and public dataset (committed)
schema.sql        the SQLite schema; radar.db itself is gitignored
sources.yaml      feeds, lookback window, manual overrides
CLAUDE.md         working rules for the model that maintains this repo
MISTAKES.md       every mistake and its fix; read at session start
```

## Privacy and conduct

Companies, funding events, founders' names and public roles, and job
postings only. No personal contact data lives in this repo, ever.
Public APIs and public pages only; no scraping of walled sites.
Corrections are welcome via GitHub issues.

MIT licensed.
