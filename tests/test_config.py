"""Pins the RADAR_ROOT / RADAR_DB isolation contract that config.py
provides, and that radar/demo.py's live-data guard depends on.

This is the fix for the 2026-06-13 incident (see MISTAKES.md): running
python -m radar.demo --db /tmp/dash.db overwrote the repo's working
issues/ and docs/ trees because --db only redirects the SQLite file, not
the artifact paths. The prevention was RADAR_ROOT, which config.ROOT
honours so that DB_PATH, ISSUES_DIR, and DOCS_DIR all relocate together
under one env var. Because config.py resolves ROOT and DB_PATH from the
environment at import time (module-level assignment, not a function),
the only faithful way to test different environments is a fresh
subprocess per environment; monkeypatching os.environ in-process and
reloading the already-imported module would not exercise the same code
path a real invocation takes.

Also pins load_sources() and load_curated_enrichment(), which degrade to
{} rather than raising when their backing files are missing.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from radar import config

REPO_ROOT = Path(__file__).resolve().parents[1]

PRINT_PATHS = (
    "import radar.config as c; "
    "print(c.ROOT); print(c.DB_PATH); "
    "print(c.ISSUES_DIR); print(c.DOCS_DIR)"
)


def _run(env_overrides):
    """Run PRINT_PATHS in a fresh interpreter with env_overrides layered on
    a clean copy of this process's environment, from the repo root so that
    'import radar.config' resolves. Returns the four printed lines."""
    env = {}
    env.update(__import__("os").environ)
    env.pop("RADAR_ROOT", None)
    env.pop("RADAR_DB", None)
    env.update(env_overrides)
    result = subprocess.run(
        [sys.executable, "-c", PRINT_PATHS],
        cwd=str(REPO_ROOT), env=env,
        capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise AssertionError("subprocess failed: %s" % result.stderr)
    lines = result.stdout.strip().splitlines()
    if len(lines) != 4:
        raise AssertionError("expected 4 printed paths, got: %r" % (lines,))
    return lines


class TestRadarRootIsolation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_radar_root_relocates_every_path_under_the_tmpdir(self):
        root, db_path, issues_dir, docs_dir = _run({"RADAR_ROOT": self.tmp})
        self.assertEqual(root, self.tmp)
        for path in (db_path, issues_dir, docs_dir):
            self.assertTrue(
                path.startswith(self.tmp + "/") or path == self.tmp,
                "%r did not relocate under %r" % (path, self.tmp))
        self.assertEqual(db_path, str(Path(self.tmp) / "radar.db"))
        self.assertEqual(issues_dir, str(Path(self.tmp) / "issues"))
        self.assertEqual(docs_dir, str(Path(self.tmp) / "docs"))

    def test_radar_db_alone_overrides_db_path_but_not_root(self):
        db_file = str(Path(self.tmp) / "scratch.db")
        root, db_path, issues_dir, docs_dir = _run({"RADAR_DB": db_file})
        # RADAR_ROOT was not set, so ROOT falls back to the real repo root;
        # only DB_PATH is redirected by RADAR_DB.
        self.assertEqual(root, str(REPO_ROOT))
        self.assertEqual(db_path, db_file)
        self.assertEqual(issues_dir, str(REPO_ROOT / "issues"))
        self.assertEqual(docs_dir, str(REPO_ROOT / "docs"))

    def test_radar_db_wins_over_the_root_derived_default(self):
        # This is the exact combination the 2026-06-13 fix relies on:
        # RADAR_ROOT relocates the artifact directories, and RADAR_DB
        # (if also set) still wins for DB_PATH rather than being
        # overridden by ROOT / "radar.db".
        other_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, other_dir, ignore_errors=True)
        db_file = str(Path(other_dir) / "elsewhere.db")
        root, db_path, issues_dir, docs_dir = _run({
            "RADAR_ROOT": self.tmp, "RADAR_DB": db_file,
        })
        self.assertEqual(root, self.tmp)
        self.assertEqual(db_path, db_file)
        self.assertNotEqual(db_path, str(Path(self.tmp) / "radar.db"))
        self.assertEqual(issues_dir, str(Path(self.tmp) / "issues"))
        self.assertEqual(docs_dir, str(Path(self.tmp) / "docs"))

    def test_neither_set_uses_the_real_repo_root(self):
        root, db_path, issues_dir, docs_dir = _run({})
        self.assertEqual(root, str(REPO_ROOT))
        self.assertEqual(db_path, str(REPO_ROOT / "radar.db"))
        self.assertEqual(issues_dir, str(REPO_ROOT / "issues"))
        self.assertEqual(docs_dir, str(REPO_ROOT / "docs"))


class TestLoadSources(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.orig_sources_path = config.SOURCES_PATH
        self.addCleanup(setattr, config, "SOURCES_PATH", self.orig_sources_path)

    def test_missing_file_returns_empty_dict(self):
        config.SOURCES_PATH = self.tmp / "does-not-exist.yaml"
        self.assertEqual(config.load_sources(), {})

    def test_existing_file_is_parsed(self):
        config.SOURCES_PATH = self.tmp / "sources.yaml"
        config.SOURCES_PATH.write_text(
            "lookback_days: 21\ncompanies_per_issue: 7\n")
        self.assertEqual(config.load_sources(),
                         {"lookback_days": 21, "companies_per_issue": 7})

    def test_empty_file_returns_empty_dict(self):
        # yaml.safe_load("") is None; load_sources normalises that to {}.
        config.SOURCES_PATH = self.tmp / "empty.yaml"
        config.SOURCES_PATH.write_text("")
        self.assertEqual(config.load_sources(), {})


class TestLoadCuratedEnrichment(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.orig_enrichment_dir = config.ENRICHMENT_DIR
        config.ENRICHMENT_DIR = self.tmp
        self.addCleanup(setattr, config, "ENRICHMENT_DIR",
                        self.orig_enrichment_dir)

    def test_missing_company_number_returns_empty_dict(self):
        self.assertEqual(config.load_curated_enrichment(None), {})
        self.assertEqual(config.load_curated_enrichment(""), {})

    def test_missing_file_returns_empty_dict(self):
        self.assertEqual(config.load_curated_enrichment("99999999"), {})

    def test_existing_file_is_parsed(self):
        data = {"one_liner": "A test company.",
                "one_liner_source": "company site (verified 2026-07-02)",
                "headcount_estimate": "11-25",
                "headcount_source": "Clay (LinkedIn-derived), 2026-07-02"}
        (self.tmp / "15396489.json").write_text(json.dumps(data))
        self.assertEqual(config.load_curated_enrichment("15396489"), data)


if __name__ == "__main__":
    unittest.main()
