"""Round-stage detection and best-effort amount parsing from press text."""

import re

IN_SCOPE_STAGES = {"pre-seed", "seed", "series-a"}

_STAGE_PATTERNS = [
    ("pre-seed", re.compile(r"\bpre[- ]?seed\b", re.IGNORECASE)),
    ("series-a", re.compile(r"\bseries\s+a\b", re.IGNORECASE)),
    ("series-b", re.compile(r"\bseries\s+b\b", re.IGNORECASE)),
    ("series-c", re.compile(r"\bseries\s+[c-h]\b", re.IGNORECASE)),
    ("growth", re.compile(r"\bgrowth\s+(round|equity)\b", re.IGNORECASE)),
    # Plain "seed" last so pre-seed wins when both words appear.
    ("seed", re.compile(r"\bseed\b", re.IGNORECASE)),
]

FUNDING_WORDS = re.compile(
    r"\b(raises?|raised|secures?|secured|lands?|landed|closes?|closed|"
    r"banks?|nets|funding|round|investment)\b",
    re.IGNORECASE,
)

_AMOUNT = re.compile(
    r"£\s*(\d+(?:[.,]\d+)?)\s*(m|million|bn|billion|k|thousand)?\b", re.IGNORECASE
)


def detect_stage(text):
    """Return the first stage label found in text, or None.
    Out-of-scope labels (series-b and later) are returned so the sieve
    can record an honest drop reason."""
    if not text:
        return None
    for label, pattern in _STAGE_PATTERNS:
        if pattern.search(text):
            return label
    return None


def mentions_funding(text):
    return bool(text and FUNDING_WORDS.search(text))


def parse_amount_gbp(text):
    """Best-effort GBP amount from press copy. Returns int pounds or None.
    Non-GBP amounts return None; we do not guess exchange rates."""
    if not text:
        return None
    m = _AMOUNT.search(text)
    if not m:
        return None
    value = float(m.group(1).replace(",", ""))
    unit = (m.group(2) or "").lower()
    if unit in ("m", "million"):
        value *= 1_000_000
    elif unit in ("bn", "billion"):
        value *= 1_000_000_000
    elif unit in ("k", "thousand"):
        value *= 1_000
    return int(value)


def format_amount(amount_gbp):
    if amount_gbp is None:
        return "undisclosed"
    if amount_gbp >= 1_000_000:
        value = amount_gbp / 1_000_000
        return "£%gm" % round(value, 1)
    return "£%dk" % round(amount_gbp / 1_000)
