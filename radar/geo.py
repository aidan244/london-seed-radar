"""Geography matching for the London gate.

All markers match on word boundaries only, never substrings:
"uk" must not match Ukraine, "england" must not match New England.
Known false-positive phrases are masked out of the text before matching.
"""

import re

from radar import config

LONDON_MARKERS = [
    "london", "greater london",
    "shoreditch", "soho", "farringdon", "clerkenwell", "hackney",
    "hackney wick", "islington", "camden", "southwark", "brixton",
    "peckham", "whitechapel", "bermondsey", "old street", "mayfair",
    "holborn", "westminster", "canary wharf", "king's cross", "kings cross",
    "dalston", "bethnal green", "vauxhall", "battersea", "stratford",
]

UK_MARKERS = ["uk", "u.k.", "united kingdom", "britain", "british", "england"]

# Phrases that contain a marker word but are not the place we mean.
# Masked (replaced with spaces) before any marker matching runs.
EXCLUSION_PHRASES = [
    "new england",
    "london, ontario",
    "london ontario",
    "east london, south africa",
    "little london",
]


def _mask_exclusions(text):
    masked = text
    for phrase in EXCLUSION_PHRASES:
        masked = re.sub(re.escape(phrase), " " * len(phrase), masked,
                        flags=re.IGNORECASE)
    return masked


def _find_marker(text, markers):
    if not text:
        return None
    masked = _mask_exclusions(text)
    for marker in markers:
        if re.search(r"\b" + re.escape(marker) + r"\b", masked, re.IGNORECASE):
            return marker
    return None


def _london_markers():
    extra = config.load_sources().get("extra_london_markers") or []
    return LONDON_MARKERS + [str(m).lower() for m in extra]


def find_london_marker(text):
    """Return the London marker found in text, or None."""
    return _find_marker(text, _london_markers())


def contains_london(text):
    return find_london_marker(text) is not None


def contains_uk(text):
    """Loose UK-level check used for triage, not for the London gate."""
    return _find_marker(text, UK_MARKERS) is not None
