"""Small shared helpers for the CLI commands."""

import datetime
import re


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


# Hard rule 2: no personal contact data anywhere in this repo. These
# shapes are checked wherever founder-adjacent text is written (enrich)
# or loaded from curated files (config), as defense in depth on top of
# the schema having no contact columns.
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"(?:\+|\b0)\d[\d\s().-]{7,}\d\b")


def looks_like_contact_data(text):
    """True when text contains an email address or a phone-number shape.
    Deliberately loose on phones (any long separated digit run after +
    or a leading 0); a rare false positive costs one skipped background
    line, a false negative publishes personal contact data."""
    if not text:
        return False
    s = str(text)
    return bool(_EMAIL.search(s) or _PHONE.search(s))
