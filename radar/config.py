"""Paths, environment loading, and sources.yaml access."""

import os
from pathlib import Path

import yaml

ROOT = Path(os.environ.get("RADAR_ROOT", Path(__file__).resolve().parents[1]))
DB_PATH = Path(os.environ.get("RADAR_DB", ROOT / "radar.db"))
SCHEMA_PATH = ROOT / "schema.sql"
SOURCES_PATH = ROOT / "sources.yaml"
FIXTURES_DIR = ROOT / "tests" / "fixtures"
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


def lookback_days(sources=None):
    sources = sources if sources is not None else load_sources()
    return int(sources.get("lookback_days", 14))
