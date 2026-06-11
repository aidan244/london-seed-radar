"""Stage 5: publish. Export the public dataset to docs/data/ (JSON and
CSV), regenerate the static archive site in docs/ (plain HTML, no build
framework) for GitHub Pages, and mark the issue published in the DB.

This command does NOT push, post, or email anything. It writes files;
the human reviews them, commits, and pushes. There is no send capability
anywhere in this repo.
"""

import argparse
import csv
import datetime
import json
import sys

import jinja2

from radar import config, db, stages, util

PUBLIC_COMPANY_FIELDS = [
    "name", "company_number", "domain", "website", "location_text",
    "incorporated_on", "one_liner", "headcount_estimate", "headcount_source",
    "ats_provider", "ats_status",
]
PUBLIC_EVENT_FIELDS = [
    "stage", "amount_gbp", "amount_source", "event_date", "filing_id",
    "status", "issue_date",
]


def _env():
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(config.TEMPLATES_DIR)),
        autoescape=True, trim_blocks=True, lstrip_blocks=True)


def export_dataset(conn, data_dir):
    rows = conn.execute(
        "SELECT fe.*, c.* FROM funding_events fe "
        "JOIN companies c ON c.id = fe.company_id "
        "WHERE fe.status IN ('featured','published') "
        "ORDER BY fe.event_date DESC").fetchall()
    companies, events = [], []
    seen = set()
    for row in rows:
        event = {k: row[k] for k in PUBLIC_EVENT_FIELDS}
        event["company_name"] = row["name"]
        events.append(event)
        if row["name"] in seen:
            continue
        seen.add(row["name"])
        company = {k: row[k] for k in PUBLIC_COMPANY_FIELDS}
        company["founders"] = [
            {"name": f["name"], "role": f["role"], "background": f["background"]}
            for f in conn.execute(
                "SELECT * FROM founders WHERE company_id = ? ORDER BY name",
                (row["company_id"],))]
        companies.append(company)

    data_dir.mkdir(parents=True, exist_ok=True)
    generated = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    for name, items in (("companies", companies), ("funding_events", events)):
        (data_dir / ("%s.json" % name)).write_text(json.dumps(
            {"generated_at": generated, "count": len(items), name: items},
            indent=2) + "\n")
    _write_csv(data_dir / "companies.csv",
               PUBLIC_COMPANY_FIELDS, companies)
    _write_csv(data_dir / "funding_events.csv",
               ["company_name"] + PUBLIC_EVENT_FIELDS, events)
    return len(companies), len(events)


def _write_csv(path, fields, items):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(items)


def _issue_entries(conn, issue_date):
    rows = conn.execute(
        "SELECT * FROM funding_events WHERE issue_date = ? "
        "AND status IN ('featured','published') ORDER BY amount_gbp DESC",
        (issue_date,)).fetchall()
    entries = []
    for event in rows:
        company = db.get_company(conn, event["company_id"])
        entries.append({
            "event": dict(event), "company": dict(company),
            "evidence": [dict(e) for e in db.event_evidence(conn, event["id"])],
            "founders": [dict(f) for f in conn.execute(
                "SELECT * FROM founders WHERE company_id = ? ORDER BY name",
                (company["id"],))],
            "jobs": [dict(j) for j in conn.execute(
                "SELECT * FROM jobs WHERE company_id = ? ORDER BY title",
                (company["id"],))],
            "amount_label": stages.format_amount(event["amount_gbp"]),
        })
    return entries


def render_site(conn, sample_data):
    env = _env()
    issues = conn.execute(
        "SELECT * FROM issues ORDER BY issue_date DESC").fetchall()
    issues_dir = config.DOCS_DIR / "issues"
    issues_dir.mkdir(parents=True, exist_ok=True)
    rendered = []
    for issue in issues:
        entries = _issue_entries(conn, issue["issue_date"])
        if not entries:
            continue
        (issues_dir / ("%s.html" % issue["issue_date"])).write_text(
            env.get_template("issue.html.j2").render(
                issue=dict(issue), entries=entries, sample_data=sample_data))
        rendered.append({"issue": dict(issue), "count": len(entries)})
    (config.DOCS_DIR / "index.html").write_text(
        env.get_template("index.html.j2").render(
            issues=rendered, sample_data=sample_data,
            generated=datetime.date.today().isoformat()))
    (config.DOCS_DIR / ".nojekyll").write_text("")
    return len(rendered)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m radar.publish", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    util.add_common_args(parser, fixtures=False, as_of=False)
    parser.add_argument("--date", default=None,
                        help="issue date to mark published (default: latest draft)")
    args = parser.parse_args(argv)

    conn = db.connect(args.db)
    db.init_db(conn)

    if args.date:
        issue = conn.execute("SELECT * FROM issues WHERE issue_date = ?",
                             (args.date,)).fetchone()
    else:
        issue = conn.execute(
            "SELECT * FROM issues WHERE status = 'draft' "
            "ORDER BY issue_date DESC LIMIT 1").fetchone()
    if issue is None:
        print("publish: no draft issue found; run python -m radar.issue first.")
        return 2

    if issue["status"] == "draft":
        conn.execute(
            "UPDATE issues SET status = 'published', published_at = ? "
            "WHERE id = ?", (datetime.datetime.now().isoformat(timespec="seconds"),
                             issue["id"]))
        for event in conn.execute(
                "SELECT id FROM funding_events WHERE issue_date = ? "
                "AND status = 'featured'", (issue["issue_date"],)).fetchall():
            db.advance_status(conn, event["id"], "published")

    sample_data = conn.execute(
        "SELECT COUNT(*) c FROM funding_events WHERE source_mode = 'fixture' "
        "AND status IN ('featured','published')").fetchone()["c"] > 0

    n_companies, n_events = export_dataset(conn, config.DOCS_DIR / "data")
    n_pages = render_site(conn, sample_data)
    conn.commit()

    print("publish: issue %s marked published in the DB" % issue["issue_date"])
    print("  dataset: docs/data/ (%d companies, %d events, JSON and CSV)"
          % (n_companies, n_events))
    print("  site:    docs/index.html plus %d issue page(s)" % n_pages)
    if sample_data:
        print("  note: dataset includes fixture-mode events; pages carry a "
              "sample-data banner")
    print("Nothing was pushed, posted, or sent. To go live: review the "
          "files, git commit, git push; GitHub Pages serves docs/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
