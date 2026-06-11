# Handover: state as of 2026-06-11

Snapshot for anyone (human or model) picking this project up. Read
CLAUDE.md and MISTAKES.md first; they are the rules. This file is the
current state and the open threads.

## Where things stand

- Repo is public at github.com/aidan244/london-seed-radar; GitHub Pages
  serves docs/ at aidan244.github.io/london-seed-radar/ (sample data
  with banner until the first real publish).
- Companies House API key: registered, in local .env, verified live
  (Monzo lookup returns 36 SH01s). Cloud agents do NOT have it.
- Working database radar.db (local only): one company enriched and
  ready, Capsa AI (£13.4m Series A, 2026-06-11, 14 live Ashby roles,
  founders still missing; pull from capsa.ai team page before
  featuring). 38 candidates dropped with recorded reasons.
- Discovery: 10 RSS feeds in sources.yaml (7 added 2026-06-11 after
  live vetting). Geography stays London-only by explicit decision.

## Decisions made (do not relitigate)

- First issue: Monday 2026-06-22. Publication day is Mondays.
- Each issue targets 10 companies (companies_per_issue in
  sources.yaml). Fewer real ones beats padding, always.
- London-specific forever; UK-wide was offered and declined.
- lookback_days is 21 only for the launch issue; revert to 14 after
  2026-06-22.
- Aim sharpened 2026-06-11: also serve students hunting internships
  and jobs at startups. Junior-role flagging and a docs/jobs.html page
  were proposed and are NOT yet approved; ask before building.

## Scheduled cloud routines (claude.ai/code/routines)

Both run in Anthropic's cloud with a fresh checkout, no key, no db, so
they are press-triage scouts only; the authoritative pipeline runs
locally. Both deliver branches plus PRs, never push to main, and have
no MCP connectors (the API auto-attached Gmail and others at creation;
they were stripped to honour the no-send rule; re-check after any
update, and watch the first runs: Fri 2026-06-12 and Sun 2026-06-14).

- trig_0186Q1yuvKW63ukqW5Qyf43L "Radar scout": Tue and Fri, cron
  0 17 * * 2,5 UTC (18:00 London in summer; 17:00 in winter, DST is
  not tracked). Writes reports/scout/<date>.md as a PR.
- trig_01KPDi3PunEJ6SuLGdPxBbHM "Radar Sunday pre-draft": Sundays,
  cron 0 7 * * 0 UTC (08:00 London in summer). Merges the week's scout
  reports with a fresh feed pull into reports/predraft/<date>.md, a
  readable digest PR, with the Sunday checklist at the bottom.

Routines cannot be deleted via API; manage at claude.ai/code/routines.

## The weekly operating loop (local, authoritative)

ingest -> sieve --dry-run (review near-misses; verify a company's
website against the press evidence before adding website_overrides;
remember TurnUp: CH name collisions can attach a London office to a
foreign startup) -> sieve -> enrich -> issue (Sunday or Monday) ->
human edits the draft -> publish -> human commits, pushes, pastes into
the newsletter, posts, messages founders -> metrics log.

## Open threads, in priority order

1. Substack account (human todo #2): blocks the 2026-06-22 issue.
2. Daily local ingest cycles to fill the pool (1 of 10 so far).
3. Fill Capsa AI founders from public team page before featuring.
4. Accelerator watchlist (Seedcamp, EF, Antler): approved discovery
   idea; pages confirmed fetchable; do it as candidate mapping for
   human review, never batch auto-resolve against CH.
5. Student features (junior-role flagging, jobs page): awaiting yes.
6. After the first issue ships: revert lookback_days to 14, git rm the
   fictional sample artifacts (issues/2026-06-10/,
   docs/issues/2026-06-10.html), and re-export.
7. Join 3 London communities (human todo #4) before launch.
