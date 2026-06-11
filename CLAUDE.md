# CLAUDE.md: London Seed Radar

Read MISTAKES.md at the start of every session, before doing anything else.

## What this project is

A public weekly briefing: every newly funded pre-seed, seed, or Series A
company in London that week, with what they do, founder backgrounds, a
headcount estimate, and live hiring signals from public ATS job boards.
Readers are founders, operators, and angels in the London early-stage
scene. The output is a markdown draft the human pastes into a newsletter
platform, plus a static archive site and public dataset served from this
repo via GitHub Pages.

The purpose is public, verifiable proof of commercial skill: subscriber
numbers, founder replies, and eventually revenue. This repo is PUBLIC on
GitHub. Everything in it is written accordingly.

## Division of labour

The model (Claude) builds and maintains the pipeline, the research
briefs, and the draft issues. The human (Aidan) does everything in the
todo categories, finalises all copy, and does all posting and sending.
The published voice is the human's; drafts are scaffolding.

The human todo tracker (`python -m radar.todo`) is the canonical list of
human steps. Some steps only a human can do: registering for API keys,
creating the newsletter account, enabling GitHub Pages, joining
communities, editing and scheduling each issue, posting to LinkedIn,
messaging founders, and logging metrics. Never automate these; never
mark them done without being told they are done.

Any message drafted for a specific founder uses Claude Opus 4.8 (model
id `claude-opus-4-8`) for the copy when available, and is sent by the
human from the human's own accounts.

## Hard rules (never violate)

1. Public repo hygiene: no secrets in code or git history, ever. The
   Companies House API key lives in `.env` (gitignored), loaded from the
   environment. `.env.example` documents the shape.
2. No personal contact data in this repo: no founder emails, no phone
   numbers, no enrichment of personal contact details. Companies,
   funding events, founders' names and public roles, and job postings
   only. The outreach CRM is a separate private project and stays
   separate. The founders table deliberately has no contact columns; do
   not add any.
3. On-demand only: every command runs, writes, exits. No daemons, no
   watchers, no background processes, no schedulers inside this repo.
4. The pipeline never publishes, posts, or sends anything. It produces
   drafts and files; a human publishes. There is no send capability
   anywhere in the code, and none may be added.
5. Public APIs and public pages only. Never scrape walled sites
   (LinkedIn, Crunchbase, PitchBook). Never trust a search snippet;
   re-fetch the live source before featuring anything.
6. SQLite (`radar.db`, gitignored) is the working source of truth; the
   public dataset is exported to `docs/data/` as JSON and CSV and
   committed. Dedup is enforced at the DB level with UNIQUE constraints
   (company number, domain).
7. Style: never use em dashes anywhere, in code, docs, or copy. Use
   commas, periods, semicolons, or colons.
8. Metrics are logged manually by the human and never estimated by
   code. They will end up on a CV; keep them honest.

## The four gates (the sieve)

Every candidate passes all four or is dropped with a recorded reason:

1. Geography: London. Location markers match on word boundaries, never
   substrings; "uk" must not match Ukraine, "england" must not match
   New England. See radar/geo.py and tests/test_geo.py.
2. Stage: pre-seed, seed, or Series A.
3. Recency: funding event inside the lookback window (default 14 days,
   set in sources.yaml).
4. Reality: live web presence and a corroborated funding event, meaning
   a Companies House filing or at least one press source.

## Issue composition

Each issue targets 10 companies (companies_per_issue in sources.yaml,
set 2026-06-11 at Aidan's request). If fewer qualify in a week, feature
the real ones and say so in the issue; never pad with unverified
companies or stretch the gates to hit the number.

## Status flow (forward-only)

discovered -> sieved -> enriched -> featured -> published, with dropped
as a terminal branch. Commands that record artifacts must never move a
status backwards; radar/db.py raises StatusFlowError on any attempt.

## Data honesty

Companies House name matches can collide: a foreign startup can share a
name with an unrelated UK company, attaching a London registered office
to the wrong funding event. Before adding a website_override to pass the
reality gate, read the press evidence and confirm the company in the
article is actually the London entity (seen live with TurnUp, Ghent,
2026-06-11).

An SH01 filing proves a raise happened and when, but the amount is often
inside an attached PDF, so amount-raised is best-effort: prefer press
figures, label filing-derived figures as statement of capital, and say
"undisclosed" rather than guess. Some Ashby orgs disable the public
posting API (the endpoint 404s while the hosted page renders); report
those as unverifiable, never guess. Headcount is a bucketed estimate
with its source stored and shown.

## Mistakes log convention

Every mistake and its fix gets appended to MISTAKES.md at the time it is
found, in the format documented there. Read MISTAKES.md at session
start. A mistake that is not logged will be repeated.
