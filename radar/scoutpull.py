"""Pull the latest cloud-scout reports onto disk so radar.leads can read
them. The reports live on PR branches (scout/<date>, predraft/<date>), not
on main, so this reads them straight from the remote-tracking refs with
git and writes reports/<kind>/<date>.md locally. Read-only against the
repo history; it only writes the report files. Runs, writes, exits.

  python -m radar.scoutpull

Degrades gracefully when git or the origin remote is unavailable.
"""

import argparse
import collections
import re
import subprocess
import sys
from pathlib import Path

from radar import config

KINDS = ("scout", "predraft")
_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*$")
_Result = collections.namedtuple("Result", "returncode stdout stderr")


def _git(args, cwd):
    try:
        return subprocess.run(["git"] + args, cwd=cwd, capture_output=True,
                              text=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return _Result(1, "", str(exc))


def _branch_date(ref):
    m = _DATE.search(ref or "")
    return m.group(1) if m else None


def report_path(kind, date):
    return "reports/%s/%s.md" % (kind, date)


def _pick_latest(refs):
    """The (ref, date) with the newest YYYY-MM-DD in its name, or None."""
    dated = [(r, _branch_date(r)) for r in refs]
    dated = [(r, d) for r, d in dated if d]
    return max(dated, key=lambda rd: rd[1]) if dated else None


def pull(root=None, git=None):
    """Write the newest scout and predraft reports into reports/. Returns the
    list of repo-relative paths written."""
    root = Path(root or config.ROOT)
    run = git or (lambda args: _git(args, str(root)))

    run(["fetch", "origin", "--quiet"])           # best-effort refresh
    written = []
    for kind in KINDS:
        refs = run(["for-each-ref", "--format=%(refname:short)",
                    "refs/remotes/origin/%s/" % kind])
        if refs.returncode != 0:
            continue
        lines = [ln.strip() for ln in refs.stdout.splitlines() if ln.strip()]
        pick = _pick_latest(lines)
        if not pick:
            continue
        ref, date = pick
        path = report_path(kind, date)
        show = run(["show", "%s:%s" % (ref, path)])
        if show.returncode != 0 or not show.stdout.strip():
            continue
        dest = root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(show.stdout)
        written.append(path)
    return written


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m radar.scoutpull", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=None,
                        help="repo root (default: the project root)")
    args = parser.parse_args(argv)

    written = pull(args.root)
    if written:
        print("scoutpull: wrote")
        for path in written:
            print("  %s" % path)
        print("Run python -m radar.ingest to pull these leads into the pool.")
    else:
        print("scoutpull: nothing pulled. No scout/predraft branches were "
              "found, or git/origin is unavailable. The reports live on PR "
              "branches; see the dashboard Cloud routines panel.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
