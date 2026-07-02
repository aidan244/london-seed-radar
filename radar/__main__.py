"""Command index for python -m radar."""

COMMANDS = [
    ("init", "create the database and seed the setup checklist"),
    ("ingest", "pull Companies House filings and RSS into candidate events"),
    ("sieve", "apply the four gates; pass or drop with a recorded reason"),
    ("enrich", "one-liner, founders, headcount, live ATS hiring check"),
    ("fillpool", "loop ingest, sieve, enrich until the pool hits the target"),
    ("scoutpull", "fetch the latest cloud-scout reports onto disk for ingest"),
    ("accelerators", "map accelerator portfolios to a review list (no DB writes)"),
    ("domains", "resolve likely websites for discovered companies"),
    ("issue", "render research briefs and the biweekly draft issue"),
    ("publish", "export the dataset and regenerate the docs/ site"),
    ("paste", "convert the edited draft to rich text for the newsletter"),
    ("todo", "the human task tracker: list, done, add, edit"),
    ("status", "one-screen overview of pipeline, issue, todos, metrics"),
    ("dashboard", "render the local progress and task control room (dashboard.html)"),
    ("metrics", "log and show subscribers, open rate, replies, revenue"),
    ("demo", "offline end-to-end run from recorded fixtures"),
    ("smoke", "one live API call per source, for when keys exist"),
]

print("London Seed Radar. Every command runs, writes, and exits;")
print("nothing here publishes, posts, or sends anything.\n")
for name, blurb in COMMANDS:
    print("  python -m radar.%-8s %s" % (name, blurb))
print("\nStart with: python -m radar.init")
