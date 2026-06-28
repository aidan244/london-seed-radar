"""Paths, environment loading, and sources.yaml access."""

import json
import os
from pathlib import Path

import yaml

ROOT = Path(os.environ.get("RADAR_ROOT", Path(__file__).resolve().parents[1]))
DB_PATH = Path(os.environ.get("RADAR_DB", ROOT / "radar.db"))
SCHEMA_PATH = ROOT / "schema.sql"
SOURCES_PATH = ROOT / "sources.yaml"
FIXTURES_DIR = ROOT / "tests" / "fixtures"
ENRICHMENT_DIR = ROOT / "enrichment"
ISSUES_DIR = ROOT / "issues"
DOCS_DIR = ROOT / "docs"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

_ENV_LOADED = False


def load_env():
    """Load KEY=VALUE lines from .env into os.environ (existing vars win).

    No python-dotenv dependency; the format here is plain KEY=VALUE.
    """
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def companies_house_key():
    load_env()
    return os.environ.get("COMPANIES_HOUSE_API_KEY", "").strip()


def load_sources():
    if not SOURCES_PATH.exists():
        return {}
    with open(SOURCES_PATH) as f:
        return yaml.safe_load(f) or {}


def load_curated_enrichment(company_number):
    """Curated live-mode enrichment override for one Companies House number,
    or {} when there is no file. Read in every mode (unlike the test
    fixtures, which load only under --fixtures), the way website_overrides
    and ats_overrides are. Public facts only; the file never holds contact
    data. Keyed by company_number, so it tracks an entity across renames."""
    if not company_number:
        return {}
    path = ENRICHMENT_DIR / ("%s.json" % company_number)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def lookback_days(sources=None):
    sources = sources if sources is not None else load_sources()
    return int(sources.get("lookback_days", 14))


def companies_per_issue(sources=None):
    sources = sources if sources is not None else load_sources()
    return int(sources.get("companies_per_issue", 5))


def issue_cadence_days(sources=None):
    """Days between issues. The briefing is biweekly, so this is 14; the
    dashboard steps the next-issue countdown forward by it."""
    sources = sources if sources is not None else load_sources()
    return int(sources.get("issue_cadence_days", 14))


def first_issue_date(sources=None):
    """Target date for the first issue as an ISO string, or None if unset."""
    sources = sources if sources is not None else load_sources()
    value = sources.get("first_issue_date")
    return str(value) if value else None
