"""The local progress dashboard: data gathering against the working
database, and a self-contained, offline, em-dash-free render."""

import argparse
import datetime
import http.client
import json
import os
import shutil
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path

from radar import config, dashboard, db

TODAY = datetime.date(2026, 6, 13)  # a Saturday; next Monday is 2 days out
NOW = datetime.datetime(2026, 6, 13, 18, 0, tzinfo=datetime.timezone.utc)

# Synthetic gh PR list (the shape fetch_routine_prs returns) for the panel.
PRS = [
    {"number": 3, "title": "Scout report 2026-06-13",
     "headRefName": "scout/2026-06-13", "createdAt": "2026-06-13T15:09:58Z",
     "state": "OPEN", "mergedAt": None, "url": "https://x/3", "isDraft": False},
    {"number": 2, "title": "RSS fetch hardening",
     "headRefName": "fix/rss-fetch-hardening", "createdAt": "2026-06-13T14:50:34Z",
     "state": "OPEN", "mergedAt": None, "url": "https://x/2", "isDraft": False},
    {"number": 1, "title": "Scout report 2026-06-12",
     "headRefName": "scout/2026-06-12", "createdAt": "2026-06-12T17:02:42Z",
     "state": "OPEN", "mergedAt": None, "url": "https://x/1", "isDraft": False},
]


def seed(conn):
    conn.execute("INSERT INTO companies (name, normalized_name) VALUES (?, ?)",
                 ("Alpha Labs", "alpha labs"))            # id 1
    conn.execute("INSERT INTO companies (name, normalized_name) VALUES (?, ?)",
                 ("Beta Health", "beta health"))          # id 2

    gates = json.dumps([{"gate": "geography", "passed": False, "detail": "Manchester"},
                        {"gate": "stage", "passed": True, "detail": "seed"}])
    events = [
        (1, "seed", 1500000, "2026-06-10", "enriched", None, None, None),
        (2, "series-a", 13400000, "2026-06-11", "featured", "2026-06-10", None, None),
        (1, "seed", None, "2026-06-02", "dropped", None, gates,
         "geography: registered office in Manchester"),
        (2, None, None, "2026-06-01", "dropped", None, None,
         "geography: outside London"),
        (1, None, None, "2026-06-12", "discovered", None, "not-json", None),
    ]
    conn.executemany(
        "INSERT INTO funding_events (company_id, stage, amount_gbp, event_date, "
        "status, issue_date, gates_json, drop_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        events)

    conn.execute("INSERT INTO issues (issue_date, path, status) VALUES (?, ?, ?)",
                 ("2026-06-10", "issues/2026-06-10/draft-issue.md", "draft"))

    conn.execute(
        "INSERT INTO human_todos (task, category, status) VALUES (?, ?, ?)",
        ("Register Companies House API key", "setup", "pending"))
    conn.execute(
        "INSERT INTO human_todos (task, category, status, issue_date, due_hint) "
        "VALUES (?, ?, ?, ?, ?)",
        ("Edit the draft issue at issues/2026-06-10/draft-issue.md and finalise "
         "the copy", "issue", "pending", "2026-06-10", "before sending"))
    conn.execute(
        "INSERT INTO human_todos (task, category, status) VALUES (?, ?, ?)",
        ("Build an accelerator watchlist", "growth", "done"))

    conn.executemany(
        "INSERT INTO metrics (date, subscribers, open_rate, "
        "replies_from_founders, revenue_gbp) VALUES (?, ?, ?, ?, ?)",
        [("2026-06-05", 30, 48.0, 1, 0.0), ("2026-06-12", 42, 51.5, 2, 0.0)])
    conn.commit()


class TestGatherDashboardData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        seed(self.conn)

    def gather(self, conn=None):
        return dashboard.gather_dashboard_data(
            conn or self.conn, sources={}, root=self.tmp, today=TODAY)

    def test_empty_db(self):
        conn = db.connect(":memory:")
        db.init_db(conn)
        data = dashboard.gather_dashboard_data(
            conn, sources={}, root=self.tmp, today=TODAY)
        self.assertEqual(data["pipeline"]["counts"], {})
        self.assertEqual(data["candidates"], [])
        self.assertEqual(data["metrics_series"], [])
        self.assertEqual(data["tasks"]["pending_count"], 0)
        self.assertIsNone(data["kpis"]["subscribers"])
        self.assertEqual(len(data["loop"]), 9)

    def test_pipeline_counts_and_drop_reasons(self):
        data = self.gather()
        self.assertEqual(data["pipeline"]["counts"],
                         {"enriched": 1, "featured": 1, "dropped": 2,
                          "discovered": 1})
        self.assertEqual(data["pipeline"]["dropped"], 2)
        self.assertEqual(data["pipeline"]["drop_reasons"],
                         [{"reason": "geography", "count": 2}])

    def test_kpis_readiness(self):
        k = self.gather()["kpis"]
        self.assertEqual(k["enriched_count"], 1)
        self.assertEqual(k["target"], 5)
        self.assertFalse(k["pool_ready"])
        self.assertEqual(k["days_to_next_monday"], 2)
        self.assertIn(k["days_to_next_monday"], range(1, 8))
        self.assertEqual(k["next_monday"], "2026-06-15")

    def test_first_issue_date_countdown(self):
        data = dashboard.gather_dashboard_data(
            self.conn, sources={"first_issue_date": "2026-06-22"},
            root=self.tmp, today=TODAY)
        k = data["kpis"]
        self.assertEqual(k["first_issue_date"], "2026-06-22")
        self.assertEqual(k["next_issue"], "2026-06-22")
        self.assertEqual(k["days_to_next_issue"], 9)     # 06-13 to 06-22

    def test_next_issue_falls_back_to_monday(self):
        # no launch date set, and a launch date already in the past
        self.assertEqual(self.gather()["kpis"]["next_issue"], "2026-06-15")
        past = dashboard.gather_dashboard_data(
            self.conn, sources={"first_issue_date": "2026-06-01"},
            root=self.tmp, today=TODAY)
        self.assertEqual(past["kpis"]["next_issue"], "2026-06-15")

    def test_biweekly_cadence_steps_from_anchor(self):
        # Past launch anchor: next issue steps forward by 14-day fortnights,
        # not to the very next Monday. 2026-06-01 + 28 days = 2026-06-29.
        data = dashboard.gather_dashboard_data(
            self.conn,
            sources={"first_issue_date": "2026-06-01", "issue_cadence_days": 14},
            root=self.tmp, today=datetime.date(2026, 6, 20))
        self.assertEqual(data["kpis"]["next_issue"], "2026-06-29")
        self.assertEqual(data["kpis"]["days_to_next_issue"], 9)

    def test_current_issue_and_loop(self):
        data = self.gather()
        self.assertEqual(data["kpis"]["current_issue_status"], "draft")
        steps = {s["key"]: s["state"] for s in data["loop"]}
        self.assertEqual(steps["issue"], "done")
        self.assertNotEqual(steps["publish"], "done")
        self.assertEqual(steps["edit"], "active")

    def test_tasks_grouping_and_commands(self):
        t = self.gather()["tasks"]
        self.assertEqual(set(t["by_category"]), {"setup", "issue", "growth"})
        self.assertEqual(t["pending_count"], 2)
        self.assertEqual(t["done_count"], 1)
        self.assertEqual(t["stale_issue_count"], 0)
        for items in t["by_category"].values():
            for it in items:
                self.assertEqual(it["done_command"],
                                 "python -m radar.todo done %d" % it["id"])

    def test_metrics_series_ordered(self):
        series = self.gather()["metrics_series"]
        self.assertEqual([r["date"] for r in series],
                         ["2026-06-05", "2026-06-12"])

    def test_candidates_gates_parsed(self):
        cands = {c["company_name"] + c["event_date"]: c
                 for c in self.gather()["candidates"]}
        dropped = cands["Alpha Labs2026-06-02"]
        self.assertEqual(dropped["status"], "dropped")
        self.assertEqual(dropped["gates"][0]["gate"], "geography")
        self.assertFalse(dropped["gates"][0]["passed"])
        # malformed gates_json degrades to an empty list, not a crash
        self.assertEqual(cands["Alpha Labs2026-06-12"]["gates"], [])

    def test_routines_panel_without_gh(self):
        # gather never calls gh; routine_prs=None renders the unavailable state
        routines = self.gather()["routines"]
        self.assertFalse(routines["gh_ok"])
        self.assertEqual(len(routines["routines"]), 2)
        self.assertEqual([r["key"] for r in routines["routines"]],
                         ["scout", "predraft"])


class TestRenderDashboard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        seed(self.conn)
        self.data = dashboard.gather_dashboard_data(
            self.conn, sources={}, root=self.tmp, today=TODAY)

    def test_self_contained_and_no_em_dash(self):
        out = os.path.join(self.tmp, "dashboard.html")
        dashboard.render_dashboard(self.data, out)
        html = Path(out).read_text()
        self.assertNotIn("—", html)   # em dash
        self.assertNotIn("–", html)   # en dash
        self.assertIn('id="dashboard-data"', html)
        self.assertNotIn("<script src", html)
        self.assertNotIn("<link href", html)
        self.assertNotIn("fetch(", html)

    def test_brand_assets_inline(self):
        out = os.path.join(self.tmp, "dashboard.html")
        dashboard.render_dashboard(self.data, out)
        html = Path(out).read_text()
        # the masthead and logo are embedded inline, not linked
        self.assertIn("London Seed Radar: biweekly briefing banner", html)
        self.assertIn("<svg", html)
        self.assertNotIn('<img', html)

    def test_refuses_to_write_into_docs(self):
        with self.assertRaises(SystemExit):
            dashboard.render_dashboard(self.data, config.DOCS_DIR / "dashboard.html")


class TestRenderModes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        seed(self.conn)
        self.data = dashboard.gather_dashboard_data(
            self.conn, sources={}, root=self.tmp, today=TODAY, routine_prs=PRS,
            now=NOW)

    def test_server_mode_has_fetch_token_and_no_em_dash(self):
        html = dashboard._render_html(self.data, server=True, token="tok123")
        self.assertIn("fetch(", html)        # live action call present
        self.assertIn("tok123", html)        # session token embedded
        self.assertIn("data-action", html)
        self.assertNotIn("—", html)
        self.assertNotIn("–", html)

    def test_static_mode_has_no_fetch(self):
        html = dashboard._render_html(self.data, server=False, token="")
        self.assertNotIn("fetch(", html)     # the static file stays offline


def _free_port():
    """Ask the OS for a currently-unused localhost port, then release it.
    There is a small, accepted TOCTOU window between this and the real
    bind in dashboard.serve(); nothing else in this test run competes for
    ports on 127.0.0.1."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestServeHttpLockdown(unittest.TestCase):
    """python -m radar.dashboard --serve's real HTTPServer/Handler wiring,
    started on an ephemeral 127.0.0.1 port in a background thread and driven
    with urllib/http.client over real sockets, offline. Pins the lockdown
    described in serve()'s docstring: a per-session token gate, the
    SERVE_ACTIONS allowlist (via run_action), and a Host-header allowlist.

    This calls the real dashboard.serve(args) (not a hand-rebuilt copy of
    its Handler), so the wiring is exactly what --serve runs. To make it
    testable from a foreground thread we: (1) swap in a HTTPServer subclass
    that records the instance serve() creates, so we get a handle to call
    .shutdown() on (serve_forever() blocks and only .shutdown() from another
    thread stops it cleanly); (2) pre-seed secrets.token_urlsafe so the
    session token is known instead of scraped from the page; (3) neutralise
    the "open a browser" side effect. All three are restored via
    addCleanup before the test ends.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db_path = os.path.join(self.tmp, "radar.db")
        conn = db.connect(self.db_path)
        db.init_db(conn)
        conn.execute(
            "INSERT INTO human_todos (task, category, status) VALUES (?, ?, ?)",
            ("Do a thing", "growth", "pending"))
        conn.commit()
        conn.close()

        created = []
        real_http_server = dashboard.HTTPServer

        class RecordingHTTPServer(real_http_server):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                created.append(self)

        orig_http_server = dashboard.HTTPServer
        dashboard.HTTPServer = RecordingHTTPServer
        self.addCleanup(setattr, dashboard, "HTTPServer", orig_http_server)

        orig_subprocess_run = dashboard.subprocess.run
        dashboard.subprocess.run = lambda *a, **kw: None
        self.addCleanup(setattr, dashboard.subprocess, "run", orig_subprocess_run)

        orig_webbrowser_open = dashboard.webbrowser.open
        dashboard.webbrowser.open = lambda *a, **kw: None
        self.addCleanup(setattr, dashboard.webbrowser, "open", orig_webbrowser_open)

        orig_token_urlsafe = dashboard.secrets.token_urlsafe
        self.token = "test-session-token-0123456789abcdef"
        dashboard.secrets.token_urlsafe = lambda *a, **kw: self.token
        self.addCleanup(setattr, dashboard.secrets, "token_urlsafe",
                        orig_token_urlsafe)

        self.port = _free_port()
        args = argparse.Namespace(db=self.db_path, port=self.port, no_prs=True)
        self.thread = threading.Thread(target=dashboard.serve, args=(args,),
                                       daemon=True)
        self.thread.start()

        deadline = time.time() + 5
        while not created and time.time() < deadline:
            time.sleep(0.02)
        self.assertTrue(created, "dashboard --serve did not start in time")
        self.httpd = created[0]
        # The token has been generated (it happens before HTTPServer(...)
        # is constructed inside serve()); restore the real generator
        # immediately rather than holding the monkeypatch for the test body.
        dashboard.secrets.token_urlsafe = orig_token_urlsafe

        self.base = "http://127.0.0.1:%d" % self.port
        self.action_url = self.base + "/action"
        self._wait_until_ready()

        def _shutdown():
            self.httpd.shutdown()   # thread-safe stop for serve_forever()
            self.thread.join(timeout=5)
        self.addCleanup(_shutdown)

    def _wait_until_ready(self):
        deadline = time.time() + 5
        last_exc = None
        while time.time() < deadline:
            try:
                urllib.request.urlopen(self.base + "/", timeout=1).close()
                return
            except Exception as exc:            # connection refused, etc.
                last_exc = exc
                time.sleep(0.02)
        raise RuntimeError("dashboard --serve never became ready: %r" % last_exc)

    def _post(self, payload):
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.action_url, data=body, method="POST",
            headers={"Content-Type": "application/json"})
        try:
            resp = urllib.request.urlopen(req, timeout=5)
            return resp.getcode(), json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_post_action_without_token_is_403(self):
        code, payload = self._post(
            {"action": "todo_done", "args": {"id": 1}})
        self.assertEqual(code, 403)
        self.assertFalse(payload["ok"])
        self.assertIn("token", payload["output"])

    def test_post_action_with_token_but_disallowed_action_is_400(self):
        code, payload = self._post({"token": self.token, "action": "rm_rf"})
        self.assertEqual(code, 400)
        self.assertFalse(payload["ok"])
        self.assertIn("not allowed", payload["output"])

    def test_post_action_with_wrong_host_header_is_rejected(self):
        body = json.dumps(
            {"token": self.token, "action": "todo_done", "args": {"id": 1}}
        ).encode("utf-8")
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.putrequest("POST", "/action", skip_host=True)
            conn.putheader("Host", "evil.example.com")
            conn.putheader("Content-Type", "application/json")
            conn.putheader("Content-Length", str(len(body)))
            conn.endheaders(body)
            resp = conn.getresponse()
            code = resp.status
            raw = resp.read()
        finally:
            conn.close()
        self.assertEqual(code, 403)
        self.assertIn(b"bad host", raw)
        # the real Host header would have let it through as a valid action
        conn2 = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn2.request("POST", "/action", body=body,
                          headers={"Content-Type": "application/json",
                                   "Host": "127.0.0.1:%d" % self.port})
            resp2 = conn2.getresponse()
            self.assertEqual(resp2.status, 200)
            resp2.read()
        finally:
            conn2.close()

    def test_get_root_returns_dashboard_html(self):
        resp = urllib.request.urlopen(self.base + "/", timeout=5)
        self.assertEqual(resp.getcode(), 200)
        self.assertIn("text/html", resp.headers.get("Content-Type", ""))
        body = resp.read().decode("utf-8")
        self.assertIn('id="dashboard-data"', body)
        self.assertIn("fetch(", body)          # server mode: live buttons
        self.assertIn(self.token, body)        # session token embedded


class TestServeActions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db_path = os.path.join(self.tmp, "radar.db")
        conn = db.connect(self.db_path)
        db.init_db(conn)
        conn.execute(
            "INSERT INTO human_todos (task, category, status) VALUES (?, ?, ?)",
            ("Do a thing", "growth", "pending"))
        conn.commit()
        conn.close()

    def test_todo_done_marks_done(self):
        res = dashboard.run_action("todo_done", {"id": 1}, self.db_path)
        self.assertTrue(res["ok"], res)
        conn = db.connect(self.db_path)
        row = conn.execute("SELECT status FROM human_todos WHERE id = 1").fetchone()
        self.assertEqual(row["status"], "done")

    def test_unknown_action_refused(self):
        res = dashboard.run_action("rm_rf", {}, self.db_path)
        self.assertFalse(res["ok"])
        self.assertIn("not allowed", res["output"])

    def test_bad_id_does_not_crash(self):
        res = dashboard.run_action("todo_done", {"id": "abc"}, self.db_path)
        self.assertFalse(res["ok"])


class TestRoutinePanel(unittest.TestCase):
    def test_on_time(self):
        panel = dashboard.routine_panel(PRS, now=NOW)
        self.assertTrue(panel["gh_ok"])
        scout, predraft = panel["routines"]
        self.assertEqual(scout["key"], "scout")
        self.assertEqual(scout["status"], "on time")     # PR #3 after last run
        self.assertEqual(len(scout["prs"]), 2)           # #3 and #1
        self.assertEqual(predraft["status"], "never")    # no predraft PRs
        self.assertTrue(scout["next_run"].endswith("UTC"))

    def test_other_prs_collects_non_routine_branch(self):
        branches = [p["branch"] for p in dashboard.routine_panel(
            PRS, now=NOW)["other_prs"]]
        self.assertIn("fix/rss-fetch-hardening", branches)

    def test_overdue(self):
        old = [{"number": 9, "title": "old", "headRefName": "scout/2026-06-09",
                "createdAt": "2026-06-09T17:00:00Z", "state": "MERGED",
                "mergedAt": "2026-06-09T18:00:00Z", "url": "https://x/9",
                "isDraft": False}]
        scout = dashboard.routine_panel(old, now=NOW)["routines"][0]
        self.assertEqual(scout["status"], "overdue")

    def test_unknown_when_gh_unavailable(self):
        panel = dashboard.routine_panel(None, now=NOW)
        self.assertFalse(panel["gh_ok"])
        self.assertEqual(panel["routines"][0]["status"], "unknown")
        self.assertEqual(panel["other_prs"], [])

    def test_cron_helpers(self):
        nxt = dashboard._cron_next(NOW, (1, 4), 17)      # Tue, Fri 17:00 UTC
        self.assertGreater(nxt, NOW)
        self.assertIn(nxt.weekday(), (1, 4))
        self.assertEqual(nxt.hour, 17)
        prev = dashboard._cron_prev(NOW, (1, 4), 17)
        self.assertLessEqual(prev, NOW)
        self.assertIn(prev.weekday(), (1, 4))


class TestIssueKeyMapping(unittest.TestCase):
    """Regression: the founder-note task text ends 'from your own email or
    LinkedIn', so a bare 'linkedin' check first misfiled it as the post
    step, showing 'Post to LinkedIn: done' when only the notes were sent."""

    def test_every_real_issue_task_maps_to_its_own_step(self):
        from radar.issue import ISSUE_TASKS
        keys = [dashboard._issue_key(task) for task, _ in ISSUE_TASKS]
        self.assertEqual(keys, ["edit", "other", "post", "message",
                                "metrics"])

    def test_founder_note_is_message_not_post(self):
        self.assertEqual(dashboard._issue_key(
            "Send a personal note to each featured founder from your own "
            "email or LinkedIn"), "message")


if __name__ == "__main__":
    unittest.main()
