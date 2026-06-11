"""Render the edited draft issue into paste-ready HTML for Substack.

Substack's editor treats pasted markdown as plain text but keeps the
formatting of pasted rich text. This converts the draft to a minimal
HTML file: open it in a browser, select all, copy, and paste into a new
Substack post. Headings, bold, lists, links, blockquotes, and dividers
carry over; Substack applies its own styling on paste.

The DRAFT banner and the paste checklist are stripped from the output,
and any scaffold placeholders still in the copy are reported so they do
not reach the editor by accident. Writes a file and exits; this command
publishes nothing and sends nothing.
"""

import argparse
import re
import subprocess
import sys

import markdown

from radar import config

DRAFT_BANNER = re.compile(r"(?s)^> DRAFT\..*?\n\n", re.MULTILINE)
CHECKLIST = re.compile(r"(?s)\n---\s*\n## 🛠️ PASTE CHECKLIST.*$")
# Scaffold placeholders look like [INTRO: ...]; markdown links are
# excluded because they are always followed by a parenthesis.
PLACEHOLDER = re.compile(r"\[[^\]]+\](?!\()")

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>%(title)s · paste into Substack</title>
<style>
  /* Styling is for the local preview only; it does not transfer. */
  body { max-width: 680px; margin: 40px auto; padding: 0 20px;
         font-family: Georgia, serif; font-size: 18px; line-height: 1.6; }
</style>
</head>
<body>
%(body)s
</body>
</html>
"""


def find_draft(issues_dir, date_arg):
    if date_arg:
        path = issues_dir / date_arg / "draft-issue.md"
        return path if path.exists() else None
    candidates = sorted(issues_dir.glob("*/draft-issue.md"), reverse=True)
    return candidates[0] if candidates else None


def prepare(text):
    """Strip scaffolding that must never be pasted; report the rest."""
    stripped = []
    if DRAFT_BANNER.search(text):
        text = DRAFT_BANNER.sub("", text)
        stripped.append("DRAFT banner")
    if CHECKLIST.search(text):
        text = CHECKLIST.sub("\n", text)
        stripped.append("paste checklist")
    leftovers = PLACEHOLDER.findall(text)
    return text, stripped, leftovers


def copy_html_to_clipboard(html_path):
    """Put the rendered file on the clipboard with an HTML flavor so
    rich-text editors (like Substack's) format it on paste. macOS only;
    plain pbcopy would paste raw markup, so this uses AppleScript.
    Returns True on success."""
    if sys.platform != "darwin":
        return False
    script = ('set the clipboard to (read (POSIX file "%s") as «class HTML»)'
              % html_path)
    try:
        subprocess.run(["osascript", "-e", script], check=True,
                       capture_output=True, timeout=10)
        return True
    except (subprocess.SubprocessError, OSError):
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m radar.paste", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", default=None,
                        help="issue date to render (default: latest draft)")
    parser.add_argument("--copy", action="store_true",
                        help="also put the rendered rich text on the "
                             "clipboard, ready to paste into Substack")
    args = parser.parse_args(argv)

    draft_path = find_draft(config.ISSUES_DIR, args.date)
    if draft_path is None:
        print("paste: no draft-issue.md found; run python -m radar.issue first.")
        return 2

    text, stripped, leftovers = prepare(draft_path.read_text())
    title = text.splitlines()[0].lstrip("# ").strip() if text else "issue"
    body = markdown.markdown(text)
    out_path = draft_path.with_name("substack-paste.html")
    out_path.write_text(PAGE % {"title": title, "body": body})

    rel = out_path.relative_to(config.ROOT)
    print("paste: wrote %s" % rel)
    if stripped:
        print("  stripped: %s" % ", ".join(stripped))
    if leftovers:
        print("  WARNING: %d scaffold placeholder(s) still in the copy; edit "
              "the draft or delete them before pasting:" % len(leftovers))
        for item in leftovers[:8]:
            print("    %s" % item)
        if len(leftovers) > 8:
            print("    ... and %d more" % (len(leftovers) - 8))
    if args.copy:
        if copy_html_to_clipboard(out_path):
            print("Rich text is on the clipboard: open a new Substack post "
                  "and paste. Nothing was published or sent.")
            return 0
        print("  clipboard copy failed (macOS only); falling back to the "
              "manual route.")
    print("Open it in a browser, select all, copy, paste into a new "
          "Substack post. Nothing was published or sent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
