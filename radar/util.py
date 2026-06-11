"""Small shared helpers for the CLI commands."""

import argparse
import datetime
import re

from radar import config


def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "company"


def parse_iso(value):
    return datetime.date.fromisoformat(value)


def add_common_args(parser, fixtures=True, as_of=True):
    parser.add_argument("--db", default=None,
                        help="path to the SQLite database (default: radar.db)")
    if fixtures:
        parser.add_argument("--fixtures", action="store_true",
                            help="run from recorded fixtures in tests/fixtures/, "
                                 "no network and no API key needed")
    if as_of:
        parser.add_argument("--as-of", default=None, metavar="YYYY-MM-DD",
                            help="treat this date as today (default: today)")
    return parser


def resolve_as_of(args):
    if getattr(args, "as_of", None):
        return parse_iso(args.as_of)
    return datetime.date.today()


def domain_of(url):
    if not url:
        return None
    m = re.match(r"https?://([^/]+)", url)
    if not m:
        return None
    return m.group(1).lower().removeprefix("www.")


def hr(title=""):
    line = "=" * 64
    return "%s\n%s\n%s" % (line, title, line) if title else line
