"""Pins radar/paste.py: find_draft's latest-dated-issue-wins selection,
and prepare()'s stripping of the DRAFT banner and the paste checklist
plus its leftover-placeholder report. copy_html_to_clipboard's AppleScript
path is platform-dependent and is not exercised here; only its non-darwin
no-op guard is pinned, with sys.platform patched so the real branch runs
regardless of the host OS and osascript is never invoked."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from radar import paste

DRAFT_TEXT = """> DRAFT. Do not publish outside the team.
> Everything here is scaffolding until edited.

# London Seed Radar · issue of 29 June 2026

[INTRO: write a short intro paragraph here]

## Alphaco

Alphaco builds useful things. Read more at [UKTN](https://example.com/press).

---
## \U0001F6E0️ PASTE CHECKLIST

- [ ] Replace INTRO placeholder
- [ ] Verify founder names
"""


class TestFindDraft(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.issues_dir = self.tmp / "issues"
        self.issues_dir.mkdir()

    def _write_draft(self, date):
        d = self.issues_dir / date
        d.mkdir()
        (d / "draft-issue.md").write_text("# issue %s\n" % date)

    def test_no_drafts_returns_none(self):
        self.assertIsNone(paste.find_draft(self.issues_dir, None))

    def test_latest_dated_issue_dir_wins(self):
        self._write_draft("2026-06-01")
        self._write_draft("2026-06-15")
        self._write_draft("2026-06-08")
        found = paste.find_draft(self.issues_dir, None)
        self.assertEqual(found, self.issues_dir / "2026-06-15" / "draft-issue.md")

    def test_explicit_date_arg_selects_that_issue(self):
        self._write_draft("2026-06-01")
        self._write_draft("2026-06-15")
        found = paste.find_draft(self.issues_dir, "2026-06-01")
        self.assertEqual(found, self.issues_dir / "2026-06-01" / "draft-issue.md")

    def test_explicit_date_arg_missing_returns_none(self):
        self._write_draft("2026-06-15")
        self.assertIsNone(paste.find_draft(self.issues_dir, "2026-06-22"))

    def test_dir_without_draft_file_is_ignored(self):
        # a directory exists but has no draft-issue.md in it; glob must
        # skip it rather than error.
        (self.issues_dir / "2026-06-20").mkdir()
        self.assertIsNone(paste.find_draft(self.issues_dir, None))


class TestPrepare(unittest.TestCase):
    def test_strips_banner_and_checklist_and_reports_leftover_placeholder(self):
        text, stripped, leftovers = paste.prepare(DRAFT_TEXT)

        self.assertIn("DRAFT banner", stripped)
        self.assertIn("paste checklist", stripped)
        self.assertNotIn("> DRAFT.", text)
        self.assertNotIn("scaffolding until edited", text)
        self.assertNotIn("PASTE CHECKLIST", text)
        self.assertNotIn("Replace INTRO placeholder", text)
        # real content survives the strip
        self.assertIn("Alphaco builds useful things", text)
        self.assertIn("[UKTN](https://example.com/press)", text)
        # the scaffold placeholder outside the checklist is reported, the
        # markdown link is not (it is followed by an open paren)
        self.assertEqual(leftovers,
                         ["[INTRO: write a short intro paragraph here]"])

    def test_no_banner_or_checklist_leaves_text_untouched(self):
        text = "# Plain issue\n\nJust body text, nothing scaffolded.\n"
        out, stripped, leftovers = paste.prepare(text)
        self.assertEqual(out, text)
        self.assertEqual(stripped, [])
        self.assertEqual(leftovers, [])

    def test_no_leftover_placeholders_reports_empty_list(self):
        text = ("> DRAFT. temp banner\n> second line\n\n"
                "# Issue\n\nAll fields filled in, no brackets here.\n")
        _, stripped, leftovers = paste.prepare(text)
        self.assertIn("DRAFT banner", stripped)
        self.assertEqual(leftovers, [])

    def test_multiple_leftover_placeholders_all_reported(self):
        text = "[FOUNDERS: tbd] some text [HEADCOUNT: tbd] more text"
        _, stripped, leftovers = paste.prepare(text)
        self.assertEqual(stripped, [])
        self.assertEqual(leftovers, ["[FOUNDERS: tbd]", "[HEADCOUNT: tbd]"])


class TestCopyHtmlToClipboardNonDarwinGuard(unittest.TestCase):
    """Only pins the non-darwin no-op guard; the AppleScript path itself is
    platform-dependent and never exercised here (osascript is never run)."""

    def test_non_darwin_returns_false_without_calling_osascript(self):
        orig_platform = sys.platform
        sys.platform = "linux"
        self.addCleanup(setattr, sys, "platform", orig_platform)
        self.assertFalse(paste.copy_html_to_clipboard("/nonexistent/path.html"))


if __name__ == "__main__":
    unittest.main()
