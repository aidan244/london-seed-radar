"""ATS job-board clients: Greenhouse, Ashby, Lever. All open JSON APIs.

Some Ashby orgs disable the public posting API: the endpoint 404s while
the hosted job page still renders. Those are reported as "unverifiable",
never guessed at. Result shape from every fetch:
{"status": "verified" | "unverifiable" | "error", "jobs": [{title, location, url}]}
"""

import json

import requests

from radar import config

TIMEOUT = 15
PROVIDERS = ("greenhouse", "ashby", "lever")


def _result(status, jobs=None):
    return {"status": status, "jobs": jobs or []}


def fetch_greenhouse(token):
    url = "https://boards-api.greenhouse.io/v1/boards/%s/jobs" % token
    return _fetch(url, _parse_greenhouse)


def fetch_ashby(org):
    url = "https://api.ashbyhq.com/posting-api/job-board/%s" % org
    return _fetch(url, _parse_ashby)


def fetch_lever(org):
    url = "https://api.lever.co/v0/postings/%s?mode=json" % org
    return _fetch(url, _parse_lever)


def _fetch(url, parser):
    try:
        resp = requests.get(url, timeout=TIMEOUT)
    except requests.RequestException:
        return _result("error")
    if resp.status_code == 404:
        return _result("unverifiable")
    if resp.status_code != 200:
        return _result("error")
    try:
        return _result("verified", parser(resp.json()))
    except Exception:
        # A 200 with any unexpected payload shape degrades to "error";
        # one malformed job entry must never crash the enrich run.
        return _result("error")


def _job(title, location, url):
    return {
        "title": title.strip() if isinstance(title, str) else title,
        "location": location.strip() if isinstance(location, str) else location,
        "url": url,
    }


def _parse_greenhouse(data):
    return [_job(j.get("title"), (j.get("location") or {}).get("name"),
                 j.get("absolute_url"))
            for j in data.get("jobs", []) if isinstance(j, dict)]


def _parse_ashby(data):
    return [_job(j.get("title"), j.get("location"),
                 j.get("jobUrl") or j.get("applyUrl"))
            for j in data.get("jobs", []) if isinstance(j, dict)]


def _parse_lever(data):
    if not isinstance(data, list):
        raise ValueError("lever payload is not a list")
    return [_job(j.get("text"), (j.get("categories") or {}).get("location"),
                 j.get("hostedUrl"))
            for j in data if isinstance(j, dict)]


_LIVE_FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "ashby": fetch_ashby,
    "lever": fetch_lever,
}

_FIXTURE_PARSERS = {
    "greenhouse": _parse_greenhouse,
    "ashby": _parse_ashby,
    "lever": _parse_lever,
}


def fetch(provider, token, fixtures=False):
    if provider not in PROVIDERS:
        raise ValueError("unknown ATS provider %r" % provider)
    if not fixtures:
        return _LIVE_FETCHERS[provider](token)
    path = config.FIXTURES_DIR / "ats" / ("%s_%s.json" % (provider, token))
    if not path.exists():
        return _result("unverifiable")
    data = json.loads(path.read_text())
    # Recorded HTTP failures, e.g. an Ashby org with the public API disabled.
    if isinstance(data, dict) and "http_status" in data:
        status = "unverifiable" if data["http_status"] == 404 else "error"
        return _result(status)
    return _result("verified", _FIXTURE_PARSERS[provider](data))
