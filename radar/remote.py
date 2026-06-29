"""Remote-role detection for hiring signals.

Now that the radar covers the whole UK, a remote-friendly role is useful
to a reader anywhere, so remote roles are surfaced inside the existing
hiring signal. The judgement is made from the job's location and title
text ONLY, so it is a hint, not a fact; everywhere the flag appears, the
copy says it was judged from the posting text and the human verifies
against the live posting before publishing. Bias is towards missing a
remote role rather than mislabelling an on-site one.
"""

import re

# Phrases that say remote on their face. "hybrid" is deliberately not
# here: hybrid roles still require on-site days, so they are not flagged
# as remote.
# "distributed" is deliberately omitted: "Distributed Systems Engineer"
# is a common on-site title, not a remote signal.
_REMOTE = re.compile(
    r"\b(remote|remote[ -]first|fully[ -]remote|work[ -]from[ -]home|"
    r"wfh|anywhere)\b", re.IGNORECASE)

# "Remote" sometimes appears negated; do not flag those.
_NOT_REMOTE = re.compile(
    r"\b(no remote|not remote|on[ -]site only|onsite only|office[ -]based)\b",
    re.IGNORECASE)


def looks_remote(*texts):
    """True if any of the given strings (location, title) suggests the role
    can be done remotely."""
    blob = " ".join(t for t in texts if t)
    if not blob or _NOT_REMOTE.search(blob):
        return False
    return bool(_REMOTE.search(blob))
