"""scoutpull's pure helpers and its pull loop with an injected git, so the
tests need no live repo: date extraction, newest-ref selection, report path
derivation, and writing the latest report per kind into reports/."""

import collections
import os
import shutil
import tempfile
import unittest

from radar import scoutpull

R = collections.namedtuple("R", "returncode stdout stderr")


class TestHelpers(unittest.TestCase):
    def test_branch_date(self):
        self.assertEqual(scoutpull._branch_date("origin/scout/2026-06-13"),
                         "2026-06-13")
        self.assertIsNone(scoutpull._branch_date("origin/main"))

    def test_report_path(self):
        self.assertEqual(scoutpull.report_path("scout", "2026-06-13"),
                         "reports/scout/2026-06-13.md")

    def test_pick_latest(self):
        ref, date = scoutpull._pick_latest(
            ["origin/scout/2026-06-12", "origin/scout/2026-06-13"])
        self.assertEqual(date, "2026-06-13")
        self.assertEqual(ref, "origin/scout/2026-06-13")
        self.assertIsNone(scoutpull._pick_latest(["origin/main"]))


class TestPull(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _fake_git(self, args):
        if args[0] == "fetch":
            return R(0, "", "")
        if args[0] == "for-each-ref":
            namespace = args[-1]
            if namespace.endswith("scout/"):
                return R(0, "origin/scout/2026-06-12\norigin/scout/2026-06-13\n", "")
            if namespace.endswith("predraft/"):
                return R(0, "origin/predraft/2026-06-14\n", "")
            return R(0, "", "")
        if args[0] == "show":
            return R(0, "# report body for %s\n" % args[1], "")
        return R(1, "", "unexpected")

    def test_pull_writes_latest_per_kind(self):
        written = scoutpull.pull(self.tmp, git=self._fake_git)
        self.assertEqual(sorted(written),
                         ["reports/predraft/2026-06-14.md",
                          "reports/scout/2026-06-13.md"])
        scout = os.path.join(self.tmp, "reports", "scout", "2026-06-13.md")
        self.assertTrue(os.path.exists(scout))
        with open(scout) as f:
            self.assertIn("report body", f.read())

    def test_pull_handles_missing_branches(self):
        written = scoutpull.pull(self.tmp, git=lambda args: R(1, "", "no git"))
        self.assertEqual(written, [])


if __name__ == "__main__":
    unittest.main()
