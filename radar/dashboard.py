"""Local progress and task control room.

  python -m radar.dashboard [--out PATH] [--open] [--no-prs]
  python -m radar.dashboard --serve [--port 8765] [--no-prs]

Renders a single self-contained HTML file from the working database plus
a little filesystem state: pipeline funnel, the issue operating loop,
the human task list, metrics over time, the candidate near-miss table,
and the progress of the scheduled cloud scout routines (read from GitHub
PRs via the gh CLI). It runs, writes one file, and exits.

With --serve it instead runs a foreground, localhost-only server so the
in-page buttons run a small allowlist of local actions (mark a todo done,
run ingest/sieve/enrich/issue) in process. That server listens until you
press Ctrl-C; it binds 127.0.0.1 only, gates every action behind a
per-session token, and never publishes, posts, or sends anything.

The output is LOCAL ONLY. It surfaces internal working state (dropped
candidates, drop reasons, todos), and this repo is public, so the file
is gitignored and never written into docs/. To refresh, re-run this
command. Nothing here publishes, posts, or sends anything.
"""

import argparse
import contextlib
import datetime
import hmac
import io
import json
import os
import re
import secrets
import subprocess
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import jinja2

from radar import config, db, stages, stats, util

# Actions the --serve server is allowed to run, in process, never via a
# shell. Deliberately excludes publish, metrics, and anything that sends.
# fill_pool loops ingest, sieve, enrich until the target or convergence;
# scout_pull fetches the latest scout reports onto disk for ingest.
SERVE_ACTIONS = ("todo_done", "ingest", "sieve", "enrich", "issue",
                 "fill_pool", "scout_pull")

# The two scheduled cloud scout routines (claude.ai/code/routines). They
# deliver GitHub PRs on these branch prefixes; weekdays use Python's
# Monday=0 numbering (cron Sun=0 is converted: Tue,Fri -> 1,4; Sun -> 6).
# Trigger IDs are account-specific identifiers, so they live in the
# gitignored .env (see .env.example), never in tracked source.
ROUTINES = [
    {"key": "scout", "name": "Radar scout", "branch_prefix": "scout/",
     "weekdays": (1, 4), "hour": 17, "cron": "0 17 * * 2,5",
     "schedule_human": "Tue and Fri, 17:00 UTC (18:00 London in summer)",
     "trigger_env": "RADAR_SCOUT_TRIGGER_ID",
     "writes": "reports/scout/<date>.md"},
    {"key": "predraft", "name": "Radar Sunday pre-draft",
     "branch_prefix": "predraft/", "weekdays": (6,), "hour": 7,
     "cron": "0 7 * * 0",
     "schedule_human": "Sundays, 07:00 UTC (08:00 London in summer)",
     "trigger_env": "RADAR_PREDRAFT_TRIGGER_ID",
     "writes": "reports/predraft/<date>.md"},
]
ROUTINES_MANAGE_URL = "https://claude.ai/code/routines"

# The issue operating loop, in order. Pipeline steps carry the command
# that drives them; the human steps (edit, post, message) carry None.
LOOP_STEPS = [
    ("ingest", "Ingest", "python -m radar.ingest"),
    ("sieve", "Sieve", "python -m radar.sieve"),
    ("enrich", "Enrich", "python -m radar.enrich"),
    ("issue", "Draft issue", "python -m radar.issue"),
    ("edit", "Edit copy", None),
    ("publish", "Publish", "python -m radar.publish"),
    ("post", "Post to LinkedIn", None),
    ("message", "Message founders", None),
    ("metrics", "Log metrics",
     "python -m radar.metrics log --subscribers N --open-rate N"),
]


def gather_dashboard_data(conn, sources=None, root=None, today=None,
                          routine_prs=None, now=None):
    """Assemble every section's state into one JSON-serializable dict.

    Pure read: pulls DB aggregates from radar.stats, builds the candidate
    rows and issue-loop steps here, and merges read-only filesystem
    state. Never writes to the database or the disk, and never touches the
    network: routine_prs is fetched by the caller (via fetch_routine_prs)
    so this stays unit-testable. routine_prs=None renders the cloud-routine
    panel in its gh-unavailable state.
    """
    sources = sources if sources is not None else config.load_sources()
    root = root if root is not None else config.ROOT
    today = today if today is not None else datetime.date.today()

    counts = stats.pipeline_counts(conn)
    issue = stats.current_issue(conn)
    metric = stats.latest_metric(conn)
    target = config.companies_per_issue(sources)
    enriched = counts.get("enriched", 0)

    days = (7 - today.weekday()) % 7 or 7
    next_monday = today + datetime.timedelta(days=days)

    # The first issue has a configured target date; count down to it, then
    # step forward by the biweekly cadence (anchored on that date so issues
    # stay on their fortnightly Mondays). With no launch date, fall back to
    # the next Monday.
    cadence = config.issue_cadence_days(sources)
    launch = config.first_issue_date(sources)
    if launch:
        anchor = datetime.date.fromisoformat(launch)
        if anchor >= today:
            next_date = anchor
        else:
            steps = (today - anchor).days // cadence + 1
            next_date = anchor + datetime.timedelta(days=steps * cadence)
        next_issue = next_date.isoformat()
        days_to_next_issue = (next_date - today).days
    else:
        next_issue = next_monday.isoformat()
        days_to_next_issue = days

    fs = _scan_filesystem(root, sources)

    return {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "db_path": str(config.DB_PATH),
        "config": fs["config"],
        "kpis": {
            "days_to_next_monday": days,
            "next_monday": next_monday.isoformat(),
            "first_issue_date": launch,
            "next_issue": next_issue,
            "days_to_next_issue": days_to_next_issue,
            "enriched_count": enriched,
            "target": target,
            "pool_ready": enriched >= target,
            "current_issue_date": issue["issue_date"] if issue else None,
            "current_issue_status": issue["status"] if issue else None,
            "subscribers": metric["subscribers"] if metric else None,
            "open_rate": metric["open_rate"] if metric else None,
            "metrics_date": metric["date"] if metric else None,
        },
        "pipeline": {
            "counts": counts,
            "order": list(db.STATUS_ORDER),
            "dropped": counts.get("dropped", 0),
            "drop_reasons": stats.drop_reasons(conn),
        },
        "loop": _issue_loop(conn, counts, issue),
        "next_step": stats.next_step_hint(conn, counts, issue),
        "tasks": _tasks(conn, issue),
        "metrics_series": stats.metrics_series(conn),
        "candidates": _candidate_rows(conn),
        "reports": fs["reports"],
        "latest_draft": fs["latest_draft"],
        "routines": routine_panel(routine_prs, now=now),
    }


def _issue_loop(conn, counts, issue):
    """Nine loop steps, each marked done, active, or todo. The first step
    that is not yet done is the active one; the rest are todo."""
    issue_todos = {}
    if issue:
        for row in conn.execute(
                "SELECT task, status FROM human_todos WHERE category = "
                "'issue' AND issue_date = ?", (issue["issue_date"],)):
            issue_todos[_issue_key(row["task"])] = row["status"]

    total = sum(counts.values())
    has_sieved = bool(counts.get("dropped")) or any(
        counts.get(s) for s in ("sieved", "enriched", "featured", "published"))
    has_enriched = any(counts.get(s) for s in ("enriched", "featured",
                                               "published"))
    published = bool(issue and issue["status"] == "published")

    done_flags = {
        "ingest": total > 0,
        "sieve": has_sieved,
        "enrich": has_enriched,
        "issue": issue is not None,
        "edit": issue_todos.get("edit") == "done",
        "publish": published,
        "post": issue_todos.get("post") == "done",
        "message": issue_todos.get("message") == "done",
        "metrics": issue_todos.get("metrics") == "done",
    }
    details = {
        "ingest": ("%d candidate(s) in the pool" % total) if total
        else "no events yet",
        "sieve": "%d sieved, %d dropped" % (
            counts.get("sieved", 0), counts.get("dropped", 0)),
        "enrich": "%d enriched" % counts.get("enriched", 0),
        "issue": ("draft %s" % issue["issue_date"]) if issue
        else "no draft yet",
        "edit": "draft finalised" if done_flags["edit"] else "human edits the copy",
        "publish": ("published %s" % issue["issue_date"]) if published
        else "not published yet",
        "post": "posted" if done_flags["post"] else "share from your account",
        "message": "founders contacted" if done_flags["message"]
        else "note to each founder",
        "metrics": "logged" if done_flags["metrics"] else "subscribers, open rate",
    }

    steps = []
    active_assigned = False
    for key, label, command in LOOP_STEPS:
        if done_flags[key]:
            state = "done"
        elif not active_assigned:
            state = "active"
            active_assigned = True
        else:
            state = "todo"
        steps.append({"key": key, "label": label, "state": state,
                      "detail": details[key], "command": command})
    return steps


def _issue_key(task):
    """Map an issue todo's task text back to its loop step key."""
    low = (task or "").lower()
    if "edit the draft" in low:
        return "edit"
    if "linkedin" in low:
        return "post"
    if "personal note" in low or "founder" in low:
        return "message"
    if "subscriber" in low or "metrics" in low or "open rate" in low:
        return "metrics"
    return "other"


def _tasks(conn, issue):
    """Human todos grouped by category, each with the exact command to
    mark it done (a static file cannot mutate the database)."""
    by_category = {"setup": [], "issue": [], "growth": []}
    pending = done = 0
    for todo in stats.all_todos(conn):
        item = {
            "id": todo["id"], "task": todo["task"],
            "category": todo["category"], "due_hint": todo["due_hint"],
            "status": todo["status"], "issue_date": todo["issue_date"],
            "done_command": "python -m radar.todo done %d" % todo["id"],
        }
        by_category.setdefault(todo["category"], []).append(item)
        if todo["status"] == "done":
            done += 1
        else:
            pending += 1

    stale = 0
    if issue:
        stale = conn.execute(
            "SELECT COUNT(*) c FROM human_todos WHERE category = 'issue' "
            "AND status = 'pending' AND issue_date < ?",
            (issue["issue_date"],)).fetchone()["c"]

    return {"by_category": by_category, "pending_count": pending,
            "done_count": done, "stale_issue_count": stale}


def _candidate_rows(conn):
    """Every funding event joined to its company, all statuses, so the
    table supports sieve --dry-run review of dropped and near-miss rows."""
    rows = conn.execute(
        "SELECT fe.id, fe.status, fe.stage, fe.amount_gbp, fe.drop_reason, "
        "fe.gates_json, fe.issue_date, fe.event_date, c.name AS company_name "
        "FROM funding_events fe JOIN companies c ON c.id = fe.company_id "
        "ORDER BY fe.event_date DESC, c.name").fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r["id"], "company_name": r["company_name"],
            "status": r["status"], "stage": r["stage"],
            "amount_gbp": r["amount_gbp"],
            "amount_label": stages.format_amount(r["amount_gbp"]),
            "drop_reason": r["drop_reason"], "issue_date": r["issue_date"],
            "event_date": r["event_date"], "gates": _parse_gates(r["gates_json"]),
        })
    return out


def _parse_gates(raw):
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return data if isinstance(data, list) else []


def fetch_routine_prs(timeout=6):
    """Recent PRs for the project repo via the gh CLI, or None if gh is
    missing, unauthenticated, offline, or slow. Read only; uses the user's
    existing gh auth. This is the dashboard's only network call."""
    fields = "number,title,headRefName,createdAt,state,mergedAt,url,isDraft"
    try:
        proc = subprocess.run(
            ["gh", "pr", "list", "--state", "all", "--limit", "30",
             "--json", fields],
            cwd=str(config.ROOT), capture_output=True, text=True,
            timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        return None
    return data if isinstance(data, list) else None


def _parse_gh_dt(value):
    if not value:
        return None
    try:
        return datetime.datetime.strptime(
            value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except (ValueError, TypeError):
        return None


def _fmt_dt(dt):
    return dt.strftime("%a %Y-%m-%d %H:%M UTC") if dt else None


def _cron_next(now, weekdays, hour):
    """The soonest UTC datetime strictly after now at hour:00 whose weekday
    is in weekdays (Python Monday=0 numbering)."""
    for offset in range(0, 14):
        cand = datetime.datetime.combine(
            (now + datetime.timedelta(days=offset)).date(),
            datetime.time(hour, tzinfo=datetime.timezone.utc))
        if cand > now and cand.weekday() in weekdays:
            return cand
    return None


def _cron_prev(now, weekdays, hour):
    """The most recent UTC datetime at or before now at hour:00 whose
    weekday is in weekdays."""
    for offset in range(0, 14):
        cand = datetime.datetime.combine(
            (now - datetime.timedelta(days=offset)).date(),
            datetime.time(hour, tzinfo=datetime.timezone.utc))
        if cand <= now and cand.weekday() in weekdays:
            return cand
    return None


def _pr_view(pr):
    return {
        "number": pr.get("number"),
        "title": pr.get("title", ""),
        "branch": pr.get("headRefName", ""),
        "created": (pr.get("createdAt") or "")[:10],
        "state": (pr.get("state") or "").upper(),
        "merged_at": (pr.get("mergedAt") or "")[:10] or None,
        "url": pr.get("url", ""),
        "draft": bool(pr.get("isDraft")),
    }


def _routine_status(prs, mine, last_expected):
    """Derive a routine's status from its PRs and the last expected run."""
    if prs is None:
        return "unknown", "gh unavailable, schedule only"
    if not mine:
        return "never", "no PR yet"
    latest = mine[0]
    created = _parse_gh_dt(latest.get("createdAt"))
    when = (latest.get("createdAt") or "")[:10]
    ref = "PR #%s, %s" % (latest.get("number"),
                          (latest.get("state") or "").lower())
    if last_expected is not None and created is not None and created >= last_expected:
        return "on time", "ran %s (%s)" % (when, ref)
    exp = _fmt_dt(last_expected) or "the last scheduled run"
    return "overdue", "no PR since %s; last was %s (%s)" % (exp, when, ref)


def routine_panel(prs, now=None):
    """Progress of the scheduled cloud scout routines, built from a list of
    GitHub PR dicts (or None when gh is unavailable). Pure: no network, no
    db. Classifies PRs to a routine by branch prefix, computes the next and
    last-expected run from the cron schedule, and derives an on-time,
    overdue, never, or unknown status per routine."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    config.load_env()   # trigger IDs live in the gitignored .env
    matched = set()
    out = []
    for spec in ROUTINES:
        mine = []
        if prs is not None:
            for pr in prs:
                if pr.get("headRefName", "").startswith(spec["branch_prefix"]):
                    matched.add(pr.get("headRefName", ""))
                    mine.append(pr)
        mine.sort(key=lambda p: p.get("createdAt", ""), reverse=True)
        last_expected = _cron_prev(now, spec["weekdays"], spec["hour"])
        status, detail = _routine_status(prs, mine, last_expected)
        out.append({
            "key": spec["key"], "name": spec["name"],
            "schedule_human": spec["schedule_human"], "cron": spec["cron"],
            "trigger_id": os.environ.get(spec["trigger_env"], "").strip()
            or "not configured (set %s in .env)" % spec["trigger_env"],
            "writes": spec["writes"],
            "next_run": _fmt_dt(_cron_next(now, spec["weekdays"], spec["hour"])),
            "last_expected": _fmt_dt(last_expected),
            "status": status, "status_detail": detail,
            "prs": [_pr_view(p) for p in mine[:5]],
        })
    other = []
    if prs is not None:
        other = [_pr_view(p) for p in prs
                 if p.get("headRefName", "") not in matched]
        other.sort(key=lambda p: p["created"], reverse=True)
    return {
        "gh_ok": prs is not None,
        "checked_at": now.strftime("%Y-%m-%d %H:%M UTC"),
        "manage_url": ROUTINES_MANAGE_URL,
        "routines": out,
        "other_prs": other[:6],
    }


def _scan_filesystem(root, sources):
    """Read-only scan: the latest issue draft, recent reports, and a
    sources.yaml summary. Tolerates missing directories."""
    root = Path(root)
    out = {"latest_draft": None, "reports": [],
           "config": _config_summary(sources)}

    issues_dir = root / "issues"
    latest = None
    if issues_dir.is_dir():
        dated = sorted((p for p in issues_dir.iterdir()
                        if p.is_dir() and _is_date(p.name)),
                       key=lambda p: p.name)
        latest = dated[-1] if dated else None
    if latest is not None:
        draft = latest / "draft-issue.md"
        briefs = latest / "briefs"
        out["latest_draft"] = {
            "issue_date": latest.name,
            "path": "issues/%s/draft-issue.md" % latest.name,
            "exists": draft.exists(),
            "briefs_count": len(list(briefs.glob("*.md"))) if briefs.is_dir() else 0,
            "mtime": _mtime(draft) if draft.exists() else None,
        }

    reports_dir = root / "reports"
    if reports_dir.is_dir():
        found = [{"title": p.stem, "path": str(p.relative_to(root)),
                  "mtime": _mtime(p)}
                 for p in reports_dir.rglob("*.md")]
        found.sort(key=lambda r: r["mtime"], reverse=True)
        out["reports"] = found[:12]
    return out


def _config_summary(sources):
    feeds = sources.get("rss_feeds") or []
    return {
        "lookback_days": config.lookback_days(sources),
        "companies_per_issue": config.companies_per_issue(sources),
        "rss_feed_count": len(feeds),
    }


def _is_date(name):
    try:
        datetime.date.fromisoformat(name)
        return True
    except ValueError:
        return False


def _mtime(path):
    return datetime.datetime.fromtimestamp(
        path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")


def _env(template_dir=None):
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(template_dir or config.TEMPLATES_DIR)),
        autoescape=True, trim_blocks=True, lstrip_blocks=True)


def _read_svg(name):
    """Read a brand SVG for inline embedding, with the XML prolog stripped
    (it is invalid inside an HTML document). Missing files return ""."""
    path = config.DOCS_DIR / "assets" / name
    if not path.exists():
        return ""
    return re.sub(r"^\s*<\?xml[^>]*\?>\s*", "", path.read_text())


def _render_html(data, server=False, token="", template_dir=None):
    """Render the dashboard to an HTML string. In server mode the page
    carries a session token and live action buttons instead of copy
    buttons; otherwise it is a static, self-contained file."""
    # type="application/json" content is parsed, not executed, so the only
    # escape needed is to neutralise a literal </script> in the data.
    data_json = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return _env(template_dir).get_template("dashboard.html.j2").render(
        data_json=data_json,
        masthead_svg=_read_svg("masthead.svg"),
        logo_svg=_read_svg("logo.svg"),
        generated=data["generated_at"],
        server=server, token=token)


def render_dashboard(data, out_path, template_dir=None):
    """Render the self-contained dashboard HTML to out_path and return it.

    Refuses any path under docs/: the dashboard carries internal state
    and must stay local and gitignored.
    """
    out_path = Path(out_path).resolve()
    docs = config.DOCS_DIR.resolve()
    if out_path == docs or docs in out_path.parents:
        raise SystemExit(
            "dashboard: refusing to write inside docs/ (%s). The dashboard "
            "shows internal working state and must stay local; pick a path "
            "outside docs/." % out_path)

    out_path.write_text(_render_html(data, template_dir=template_dir))
    return str(out_path)


def run_action(action, args, db_path):
    """Run one allowlisted local action in process and capture its output.

    Only the actions in SERVE_ACTIONS are permitted; everything else is
    refused. Actions run by calling the pipeline module mains directly,
    never via a shell, so there is no command-injection surface. Nothing
    here publishes, posts, or sends.
    """
    if action not in SERVE_ACTIONS:
        return {"ok": False, "output": "action not allowed: %s" % action}
    base = ["--db", db_path] if db_path else []
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            if action == "todo_done":
                from radar import todo
                rc = todo.main(base + ["done", str(int(args.get("id")))])
            elif action == "scout_pull":
                from radar import scoutpull
                rc = scoutpull.main([])          # reads the project root
            else:
                from radar import enrich, fillpool, ingest, issue, sieve
                rc = {"ingest": ingest, "sieve": sieve, "enrich": enrich,
                      "issue": issue, "fill_pool": fillpool}[action].main(base)
    except (ValueError, TypeError) as exc:
        return {"ok": False, "output": "bad arguments: %s" % exc}
    except Exception as exc:                 # surface, do not crash the server
        return {"ok": False, "output": "error: %s" % exc}
    out = buf.getvalue().strip()
    return {"ok": rc in (0, None), "output": out or ("done (rc=%s)" % rc)}


def serve(args):
    """Run a foreground, localhost-only server so the dashboard buttons run
    allowlisted local actions. This is the one mode that is not a
    runs-writes-exits command: it listens until you press Ctrl-C. It binds
    127.0.0.1 only, gates every action behind a per-session token, and
    never publishes, posts, or sends."""
    token = secrets.token_urlsafe(24)
    db_path = args.db
    host, port = "127.0.0.1", args.port
    hosts_ok = {"%s:%d" % (host, port), "localhost:%d" % port}

    def current_html():
        conn = db.connect(db_path)
        db.init_db(conn)
        prs = None if args.no_prs else fetch_routine_prs()
        data = gather_dashboard_data(conn, routine_prs=prs)
        conn.close()
        return _render_html(data, server=True, token=token).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code, obj):
            self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

        def do_GET(self):
            if self.path.split("?", 1)[0] not in ("/", "/index.html"):
                self.send_error(404)
                return
            self._send(200, current_html(), "text/html; charset=utf-8")

        def do_POST(self):
            if self.path != "/action":
                self.send_error(404)
                return
            if self.headers.get("Host", "") not in hosts_ok:
                self.send_error(403, "bad host")
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except ValueError:
                self._json(400, {"ok": False, "output": "bad json"})
                return
            if not hmac.compare_digest(str(payload.get("token", "")), token):
                self._json(403, {"ok": False, "output": "bad token"})
                return
            action = payload.get("action", "")
            aargs = payload.get("args") or {}
            print("dashboard --serve: run %s %s" % (action, aargs or ""))
            result = run_action(action, aargs, db_path)
            tail = (result["output"].splitlines() or [""])[-1]
            print("  -> %s" % (tail if result["ok"] else result["output"]))
            self._json(200 if result["ok"] else 400, result)

        def log_message(self, *a):
            pass                    # quiet; actions are printed above

    httpd = HTTPServer((host, port), Handler)
    url = "http://%s:%d/" % (host, port)
    print("dashboard --serve: live at %s" % url)
    print("  127.0.0.1 only, token gated. Buttons run allowlisted local")
    print("  actions: todo done, ingest, sieve, enrich, issue.")
    print("  It never publishes, posts, or sends. Press Ctrl-C to stop.")
    if sys.platform == "darwin":
        subprocess.run(["open", url], check=False)
    else:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\ndashboard --serve: stopped.")
    finally:
        httpd.server_close()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m radar.dashboard", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    util.add_common_args(parser, fixtures=False, as_of=False)
    parser.add_argument(
        "--out", default=str(config.ROOT / "dashboard.html"),
        help="where to write the HTML (default: ./dashboard.html, gitignored)")
    parser.add_argument(
        "--open", action="store_true", dest="open_browser",
        help="open the file in your browser after writing")
    parser.add_argument(
        "--serve", action="store_true",
        help="run a localhost-only server so the buttons run actions "
             "(Ctrl-C to stop)")
    parser.add_argument(
        "--port", type=int, default=8765,
        help="port for --serve (default 8765)")
    parser.add_argument(
        "--no-prs", action="store_true",
        help="skip the gh call for cloud-routine PR status (offline)")
    args = parser.parse_args(argv)

    if args.serve:
        return serve(args)

    conn = db.connect(args.db)
    db.init_db(conn)
    prs = None if args.no_prs else fetch_routine_prs()
    data = gather_dashboard_data(conn, routine_prs=prs)
    out = render_dashboard(data, args.out)

    print("dashboard: wrote %s" % out)
    print("  local only, gitignored; it shows internal state, never publish it.")
    print("  refresh by re-running python -m radar.dashboard")
    if args.open_browser:
        if sys.platform == "darwin":
            subprocess.run(["open", out], check=False)
        else:
            print("  open it manually: file://%s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
