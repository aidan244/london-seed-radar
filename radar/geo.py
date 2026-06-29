"""Geography matching for the UK gate, London first.

Scope is UK-wide; London is detected separately so issues can lead with
London raises and group the rest of the UK after them. Every marker
matches on word boundaries only, never substrings: "uk" must not match
Ukraine, "england" must not match New England. Known false-positive
phrases (including UK city names that collide with US cities, e.g.
"Cambridge, MA") are masked out of the text before matching.

City names alone are best effort: a registered office from Companies
House carries a UK postcode and a nation name, which are the reliable
signals; a press snippet that only says "Cambridge" could be the wrong
country, so the US collisions are masked and the human re-checks the
live source before featuring, per the reality gate.
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

# Nation-level markers: reliable, no UK/US collisions once Ukraine and
# New England are masked.
UK_MARKERS = [
    "uk", "u.k.", "united kingdom", "great britain", "britain", "british",
    "england", "scotland", "scottish", "wales", "welsh",
    "northern ireland",
]

# UK startup hubs outside London. Several collide with US cities, so the
# US "City, State" forms are masked first (see EXCLUSION_PHRASES) and a
# city match is treated as best effort, not proof.
# "reading" and "bath" are deliberately omitted: as common English words
# they would match ordinary copy ("reading research", "bath products").
UK_CITY_MARKERS = [
    "manchester", "birmingham", "leeds", "bristol", "sheffield",
    "liverpool", "newcastle", "nottingham", "leicester", "coventry",
    "edinburgh", "glasgow", "aberdeen", "dundee", "cardiff", "swansea",
    "belfast", "cambridge", "oxford", "brighton",
    "norwich", "york", "exeter", "milton keynes",
]

# A full UK postcode (outward + inward), space optional. Registered
# offices from Companies House always carry one, so this is the strongest
# non-London UK signal and never collides with US locations.
UK_POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}\b", re.IGNORECASE)

# Phrases that contain a marker word but are not the place we mean.
# Masked (replaced with spaces) before any marker matching runs.
EXCLUSION_PHRASES = [
    "new england",
    "london, ontario",
    "london ontario",
    "east london, south africa",
    "little london",
    # UK city names that collide with US cities, in the common
    # "City, State" press form. Masking the whole phrase removes the
    # city token so it cannot pass the UK gate on its own.
    "cambridge, ma", "cambridge, massachusetts",
    "manchester, nh", "manchester, new hampshire",
    "birmingham, al", "birmingham, alabama",
    "oxford, ms", "oxford, mississippi", "oxford, ohio",
    "bristol, ct", "bristol, tn", "bristol, va", "bristol, pa",
    "brighton, ma", "brighton, mi",
    "glasgow, ky", "glasgow, mt",
    "york, pa", "new york",
]


def _mask_exclusions(text):
    masked = text
    for phrase in EXCLUSION_PHRASES:
        masked = re.sub(re.escape(phrase), " " * len(phrase), masked,
                        flags=re.IGNORECASE)
    return masked


def _search_markers(masked, markers):
    for marker in markers:
        if re.search(r"\b" + re.escape(marker) + r"\b", masked, re.IGNORECASE):
            return marker
    return None


def _find_marker(text, markers):
    if not text:
        return None
    return _search_markers(_mask_exclusions(text), markers)


def _london_markers():
    extra = config.load_sources().get("extra_london_markers") or []
    return LONDON_MARKERS + [str(m).lower() for m in extra]


def _uk_markers():
    extra = config.load_sources().get("extra_uk_markers") or []
    return UK_MARKERS + UK_CITY_MARKERS + [str(m).lower() for m in extra]


def find_london_marker(text):
    """Return the London marker found in text, or None."""
    return _find_marker(text, _london_markers())


def contains_london(text):
    return find_london_marker(text) is not None


def find_uk_marker(text):
    """Return a non-London UK marker found in text, or None. Checks nation
    and city names first, then falls back to a UK postcode."""
    if not text:
        return None
    masked = _mask_exclusions(text)
    marker = _search_markers(masked, _uk_markers())
    if marker:
        return marker
    if UK_POSTCODE.search(masked):
        return "uk postcode"
    return None


def locate(text):
    """Classify text for the geography gate. Returns (region, marker) where
    region is 'london', 'uk', or None. London takes priority so issues can
    lead with London and group the rest of the UK after it."""
    marker = find_london_marker(text)
    if marker:
        return "london", marker
    marker = find_uk_marker(text)
    if marker:
        return "uk", marker
    return None, None


# Explicit non-UK headquarters signals. A press snippet that calls a company
# "Berlin-based" or "the Swedish developer" is asserting a foreign HQ, so an
# attached UK registered office is probably a same-name match (the TurnUp
# lesson) and the geography gate vetoes it. Deliberately conservative: only
# HQ-asserting forms count, not a passing mention of a foreign city or a
# foreign co-founder of a UK company.
FOREIGN_PLACES = [
    "berlin", "munich", "hamburg", "frankfurt", "cologne", "stockholm",
    "gothenburg", "paris", "lyon", "amsterdam", "rotterdam", "madrid",
    "barcelona", "milan", "rome", "copenhagen", "helsinki", "oslo", "zurich",
    "geneva", "vienna", "brussels", "lisbon", "porto", "warsaw", "tallinn",
    "dublin", "new york", "san francisco", "boston", "los angeles", "chicago",
    "singapore", "tel aviv", "toronto", "sydney", "bangalore", "mumbai",
    "germany", "sweden", "france", "netherlands", "spain", "italy", "denmark",
    "finland", "norway", "switzerland", "austria", "belgium", "portugal",
    "poland", "estonia", "ireland", "united states", "u.s.", "usa", "canada",
    "australia", "israel", "india",
]
FOREIGN_NATIONALITIES = [
    "german", "swedish", "french", "dutch", "spanish", "italian", "danish",
    "finnish", "norwegian", "swiss", "austrian", "belgian", "portuguese",
    "polish", "estonian", "irish", "american", "canadian", "australian",
    "israeli", "indian", "singaporean",
]
_COMPANY_NOUN = (r"(?:company|companies|startup|start-up|scale-?up|firm|"
                 r"business|developer|maker|manufacturer|group|venture|"
                 r"fintech|biotech|platform|app)")
# No word boundary after "based": press snippets often lose spaces
# ("Berlin-basedmanufacturing"), and the foreign place plus "-based" is
# already distinctive enough.
_FOREIGN_BASED = re.compile(
    r"\b(?:" + "|".join(re.escape(p) for p in FOREIGN_PLACES) + r")[- ]based",
    re.IGNORECASE)
_FOREIGN_NAT = re.compile(
    r"\bthe\s+(?:" + "|".join(FOREIGN_NATIONALITIES) + r")\s+" + _COMPANY_NOUN,
    re.IGNORECASE)
_FOREIGN_IN = re.compile(
    r"\b(?:headquartered|based|hq)\s+in\s+(?:" +
    "|".join(re.escape(p) for p in FOREIGN_PLACES) + r")\b", re.IGNORECASE)


def find_foreign_hq(text):
    """Return a phrase asserting a non-UK headquarters, or None. Matches
    '<place>-based', 'the <nationality> <company-noun>', and 'based or
    headquartered in <foreign place>'; not an incidental city mention or a
    foreign co-founder. Used by the sieve to veto a London office that a
    same-name UK entity attached to a foreign funding event."""
    if not text:
        return None
    # No exclusion masking here: that mask blanks "new york" to stop it
    # passing the UK gate, but for foreign detection "New York-based" should
    # match, not be hidden.
    for rx in (_FOREIGN_BASED, _FOREIGN_NAT, _FOREIGN_IN):
        m = rx.search(text)
        if m:
            return m.group(0).strip()
    return None


def classify_region(text):
    """Return 'london', 'uk', or None for the geography gate."""
    return locate(text)[0]


def contains_uk(text):
    """True if text names anywhere in the UK, London included. Used for
    triage and the geography gate."""
    return classify_region(text) is not None


def combine_evidence_text(location_text, evidence):
    """Join the registered-office location with every evidence title and
    snippet into one string for marker matching. evidence rows are
    mapping-like with 'title' and 'snippet' keys. Sieve and issue use this
    so the geography verdict is computed from identical text in both."""
    parts = [location_text]
    for row in evidence:
        parts.append(row["title"])
        parts.append(row["snippet"])
    return " ".join(filter(None, parts))
