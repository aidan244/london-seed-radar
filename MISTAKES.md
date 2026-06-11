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
