# Mistakes log

Convention: every mistake made while building or operating this project
gets an entry, appended at the time it is found. Read this file at the
start of every session. Entries are never deleted; a mistake that is
not logged will be repeated.

Format:

```
## YYYY-MM-DD: short title
- What happened:
- Why:
- Fix:
- Prevention:
```

## 2026-06-10: re-ingest crashed on dropped events
- What happened: running ingest a second time raised
  sqlite3.IntegrityError on UNIQUE(company_id, event_date).
- Why: find_or_create_event excluded dropped events from merge
  matching, so the same filing tried to insert a duplicate row instead
  of merging into the already-dropped event.
- Fix: merge matching now considers all events regardless of status; a
  dropped event absorbs the repeat observation and stays dropped.
- Prevention: regression test test_reingest_merges_into_dropped_events;
  every command must be assumed to re-run over existing data.

## 2026-06-10: jinja trim_blocks ate markdown blank lines
- What happened: the draft issue rendered with field lines glued to the
  next heading, producing invalid markdown.
- Why: with trim_blocks on, a line ending in an inline block tag (for
  example an inline endfor) loses its newline.
- Fix: display strings are precomputed in radar/issue.py and the
  template emits a tight bullet list that needs no blank-line juggling.
- Prevention: keep logic out of markdown templates; render and read the
  artifact before calling a template done.

## 2026-06-13: demo run overwrote the working draft and regenerated docs
- What happened: while verifying the new radar.dashboard command I ran
  python -m radar.demo --db /tmp/dash.db, expecting --db to sandbox it. It
  is not sandboxed: demo always writes issues/2026-06-10/ and docs/ via
  config.ISSUES_DIR and config.DOCS_DIR. It overwrote the uncommitted
  working-tree edit to issues/2026-06-10/draft-issue.md (now back to the
  committed sample) and regenerated docs/data/ and docs/*.html.
- Why: demo hardcodes DEMO_AS_OF and calls issue.main then publish.main,
  which write to the repo's issues/ and docs/ dirs. --db only redirects
  the SQLite file, not the artifact paths. The dashboard plan's
  verification step wrongly assumed --db isolated demo.
- Fix: restored docs/ to HEAD with git checkout. The draft's unstaged
  edit could not be recovered (overwritten before this session committed
  it); it now matches HEAD. The dashboard itself only reads; it never
  writes to the repo except the gitignored dashboard.html.
- Prevention: to run demo or any pipeline command in isolation, set
  RADAR_ROOT to a temp dir (config.ROOT honours it, so docs/, issues/,
  and radar.db all relocate together), for example
  RADAR_ROOT=/tmp/radar-scratch python -m radar.demo. Never run
  demo/publish/issue against the live repo just to populate a scratch db.

## 2026-06-28: ingest crashed on a non-ISO lead date from a predraft
- What happened: re-running python -m radar.ingest after scoutpull threw
  ValueError: Invalid isoformat string: 'approx. 10 June 2026 (featured in
  UKTN June 8-12 roundup)'. The predraft prose fallback in radar/leads.py
  passed that string straight through as published_date, and ingest's
  find_or_create_event handed it to util.parse_iso (date.fromisoformat),
  which only accepts YYYY-MM-DD. One bad date aborted the whole ingest.
- Why: RSS items emit ISO dates (rssfeeds strftime %Y-%m-%d), so the rest
  of the pipeline assumes published_date is ISO. The prose lead parser
  never normalised the human dates it scrapes ("17 June 2026", or qualified
  prose like the above), so it silently violated that contract.
- Fix: added leads._iso_date to normalise ISO, "DD Month YYYY",
  "Month DD, YYYY", and a date embedded in prose, returning None when no
  real date is recoverable so the lead is dropped (a dateless lead can't
  pass recency anyway) instead of crashing ingest. _item routes
  published_date through it. Regression tests in tests/test_leads.py.
- Prevention: any field a gate or parse_iso consumes must be normalised at
  the source that produces it (leads, feeds), to the same shape RSS emits;
  never pass scraped prose into date.fromisoformat.

## 2026-06-28: brand-renamed company lost its website_override key
- What happened: after resolving leads to verified Companies House numbers,
  Conduct / Isometric / Record OS still dropped on the reality gate ("no
  website found") despite website_overrides keyed by their brand names.
- Why: ingest_filings creates the company under its register name
  (CONDUCT AI LTD -> normalized_name "conduct ai"); ingest_press then
  renamed the display name to the brand ("Conduct") but left
  normalized_name as "conduct ai". resolve_website looks up overrides by
  normalized_name, so the brand-keyed override ("conduct") never matched.
- Fix: ingest_press now updates normalized_name alongside name when it
  applies the brand display name, so brand-keyed website_overrides and
  ats_overrides resolve. normalized_name is not UNIQUE, so this is safe.
- Prevention: when display name and normalized_name can diverge, keep them
  in sync; overrides are keyed by the normalized brand, not the register.

## 2026-06-29: a lead's url was the company homepage, shown as press evidence
- What happened: the first biweekly draft rendered evidence links like
  "[UKTN (lead)](https://capsa.ai)": the link text named a press source but
  the href was the company's own marketing homepage, not the funding story.
- Why: the manual leads added to sources.yaml set source: UKTN but used the
  company homepage as the lead url. ingest passes that url straight into the
  press evidence, and issue.py renders "[source_name](url)". Homepage as
  evidence undercuts the reality gate (a corroborated event needs a filing
  or press source) and the whole "verifiable proof" purpose.
- Fix: pointed each lead url at the actual UKTN funding article; the
  homepage stays only in website_overrides (where the reality gate needs a
  live site). Caught by the adversarial review workflow, not by tests.
- Prevention: a lead's url is its corroborating press article, never the
  company site. Keep the site in website_overrides, the article in the lead.

## 2026-06-29: cadence sweep missed the static masthead brand asset
- What happened: converting the briefing from weekly to biweekly updated
  templates and Python copy but left docs/assets/masthead.svg saying
  "WEEKLY BRIEFING" (visible pill, aria-label, and issue line), which the
  dashboard inlines and the human exports as the email banner.
- Why: the masthead is a hand-maintained SVG plus two rasterised PNGs, not
  generated from a template, so a grep-and-edit sweep of templates and code
  skipped it. A test (test_brand_assets_inline) pinned the stale aria-label,
  so the suite stayed green while the asset was wrong.
- Fix: updated the SVG pill to "BIWEEKLY BRIEFING" (widened the pill rect so
  the longer word fits), aria-label, and the sample issue line, re-exported
  both PNGs with rsvg-convert, and updated the test assertion.
- Prevention: when changing brand copy, include hand-maintained assets
  (docs/assets/*.svg and their PNG exports) in the sweep, not just templates;
  a test that asserts an exact asset string can hide a stale asset.

## 2026-06-30: pushed a merge commit to a linear-history-protected main
- What happened: after landing the biweekly work to publish the archive, the
  first `git push origin main` was rejected ("protected branch hook declined,
  Found 1 violation"). main had just been branch-protected, and the push
  contained a merge commit, which the protection forbids.
- Why: I integrated the feature branch with `git merge --no-ff`, creating a
  merge commit. main now has required_linear_history=true with
  enforce_admins=true, so merge commits are rejected even for the owner.
- Fix: re-landed the identical, already-verified tree as linear history by
  cherry-picking the seven feature commits onto origin/main (c4190d3),
  resolving the docs/ modify-delete conflicts in favour of the freshly
  published site, then pushed a clean fast-forward (origin/main ee415bb).
  Confirmed the linear tree was byte-identical to the merge tree first
  (git diff f30cca5 HEAD was empty).
- Prevention: main requires LINEAR history. Never `git merge` into main;
  rebase or cherry-pick so the push is linear. Check protection first with
  gh api repos/aidan244/london-seed-radar/branches/main/protection.

## 2026-06-30: a personal absolute path got committed to the public repo
- What happened: a safety audit of the public repo found
  reports/substack-setup-prompt.md line 20 carried a hardcoded local path
  (the absolute macOS home-directory path to the repo's docs/assets/
  folder), exposing the machine username and Desktop layout. It was the
  only personal/dangerous item the audit surfaced (no secrets, no founder
  contact data, no dangerous code).
- Why: the prompt was written with the real local asset path so the human
  could find the files, then committed as working scaffolding without a
  pass for machine-specific paths. Hard Rule 1 forbids personal machine
  detail in the public repo, but nothing checked for it before commit.
- Fix: untracked the file (git rm --cached, kept the local copy) along with
  two other standalone internal prompts, and gitignored all three; the rest
  of reports/ stays tracked because the pipeline reads it. Severity was low
  (no credential; the username is already public via the Substack and
  GitHub handles), so no history rewrite. Pushed linear (origin/main
  b72285b).
- Prevention: before committing anything under reports/ or any prose with
  file paths, grep the staged tree for home paths:
  git grep --cached -nE '/(Users|home)/[a-z]+' returns nothing (the grouped
  pattern is deliberate: it cannot match its own recipe text). Use relative
  paths in prompts/notes that will be tracked; keep absolute local paths in
  gitignored files only.

## 2026-07-02: the leak fix quoted the leaked path verbatim
- What happened: the 2026-06-30 MISTAKES entry documenting the personal
  path leak reproduced the exact absolute path in its own text, so the
  string the fix removed from reports/ was re-published on public main in
  this tracked file. Found by the 2026-07-02 repo audit. The same audit
  found the untracked-on-main prompt file still tracked on 11 stale remote
  PR branches.
- Why: the entry was written to be precise about what leaked, and nothing
  in the convention said to describe a leaked value by location rather than
  by value. The prevention grep in that entry also could not pass again,
  because the entry itself matched it, which made the check useless.
- Fix: reworded the 2026-06-30 entry to describe the path without quoting
  it (entries are never deleted; the meaning is preserved); switched the
  prevention pattern to a grouped regex that cannot match its own recipe;
  closed the 12 stale PRs, preserved their seven scout/predraft reports on
  main, and deleted the 11 branches that served the old file.
- Prevention: when logging a leak in this file, describe it by file, line,
  and kind, never by value; a remediation is not complete until every
  public ref stops serving the string, not just HEAD of main.

## 2026-07-03: the audit found four gate and honesty defects in shipped code
- What happened: a function-level audit (report untracked at the repo
  root, RADAR_AUDIT_2026-07-02.md) confirmed four high-severity defects
  that had shipped: the geography gate passed "New South Wales" and
  "British Columbia" as UK and vetoed "Northern Ireland-based" as
  foreign; parse_amount_gbp read £1,500,000 as £1,500; and a re-ingest
  could silently rewrite stage, amount, and date on already-published
  events. A cluster of crash and idempotence bugs sat exactly in the 13
  modules with no dedicated tests, including publish.py, the code that
  keeps contact data out of the public dataset.
- Why: marker lists were only ever checked against the collisions someone
  had already thought of; the status guard protected the status column
  and nothing else; and untested modules stayed untested because the demo
  exercised their happy path, which reads as coverage.
- Fix: all confirmed findings fixed across ~30 commits on 2026-07-03,
  each with a regression test; the suite grew from 160 to 329 tests, and
  every hard-rule behaviour (public-dataset field allowlist, ATS 404
  honesty, RADAR_ROOT isolation, serve lockdown, forward-only for issues
  as well as events) now has a test fence.
- Prevention: an absent guard is a finding even when no function contains
  it; when adding a geography marker, hunt its containing phrases before
  trusting word boundaries; any invariant worth a docstring gets a test
  that fails when the invariant regresses, not a demo that passes while
  it holds.
