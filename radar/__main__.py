"""Command index for python -m radar."""

COMMANDS = [
    ("init", "create the database and seed the setup checklist"),
    ("ingest", "pull Companies House filings and RSS into candidate events"),
    ("sieve", "apply the four gates; pass or drop with a recorded reason"),
    ("enrich", "one-liner, founders, headcount, live ATS hiring check"),
    ("issue", "render research briefs and the weekly draft issue"),
    ("publish", "export the dataset and regenerate the docs/ site"),
    ("todo", "the human task tracker: list, done, add"),
    ("status", "one-screen overview of pipeline, issue, todos, metrics"),
    ("metrics", "log and show subscribers, open rate, replies, revenue"),
    ("demo", "offline end-to-end run from recorded fixtures"),
    ("smoke", "one live API call per source, for when keys exist"),
]

print("London Seed Radar. Every command runs, writes, and exits;")
print("nothing here publishes, posts, or sends anything.\n")
for name, blurb in COMMANDS:
    print("  python -m radar.%-8s %s" % (name, blurb))
print("\nStart with: python -m radar.init")
