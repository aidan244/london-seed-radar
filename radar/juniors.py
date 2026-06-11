"""Junior-role detection for hiring signals.

Approved 2026-06-11: flag roles a recent grad could plausibly apply
for. The judgement is made from the job title ONLY, so it is a hint,
not a fact; everywhere the flag appears, the copy says it was judged
from the title and the human verifies against the live posting before
publishing. Bias is towards missing a junior role rather than
mislabelling a senior one.
"""

import re

# Titles that say junior on their face.
_ALWAYS = re.compile(
    r"\b(intern|interns|internship|graduate|grad|junior|trainee|"
    r"apprentice|placement|entry[ -]level)\b", re.IGNORECASE)

# Titles that are usually early-career unless a seniority word says
# otherwise ("Lab Operations Associate" yes, "Associate Director" no).
_MAYBE = re.compile(r"\b(associate|analyst)\b", re.IGNORECASE)
_SENIORITY = re.compile(
    r"\b(senior|sr|staff|principal|lead|head|director|vp|"
    r"vice president|chief|founding|partner|executive)\b", re.IGNORECASE)


def looks_junior(title):
    """True if the title alone suggests a recent grad could apply."""
    if not title:
        return False
    if _ALWAYS.search(title):
        return True
    return bool(_MAYBE.search(title) and not _SENIORITY.search(title))
