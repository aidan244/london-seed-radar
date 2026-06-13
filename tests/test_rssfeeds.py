"""Offline tests for RSS triage: saved-file parsing and the funding/name
filters. No network; everything runs from tests/fixtures/rss/. This is the
path the WebFetch-based cloud scout reuses via load_from_dir."""

import urllib.parse

from radar import config, rssfeeds


def _by_name(items):
    return {item["company_name"]: item for item in items}


def test_load_from_dir_triages_fixture_feeds():
    items = rssfeeds.load_from_dir(config.FIXTURES_DIR / "rss")
    by_name = _by_name(items)
    # Funding-shaped headlines across both fixture feeds are picked up.
    assert "Marrowbone Robotics" in by_name
    assert "Quillstone AI" in by_name
    assert "Hedgerow Labs" in by_name


def test_stage_and_amount_parsed_from_headline():
    by_name = _by_name(rssfeeds.load_from_dir(config.FIXTURES_DIR / "rss"))
    marrowbone = by_name["Marrowbone Robotics"]
    assert marrowbone["stage"] == "series-a"
    assert marrowbone["amount_gbp"] == 8_500_000
    quillstone = by_name["Quillstone AI"]
    assert quillstone["stage"] == "pre-seed"
    assert quillstone["amount_gbp"] == 750_000


def test_non_gbp_amount_is_not_guessed():
    by_name = _by_name(rssfeeds.load_from_dir(config.FIXTURES_DIR / "rss"))
    # Dollar rounds are still triaged (name + funding words) but carry no
    # GBP amount; we never guess an exchange rate.
    granite = by_name.get("Granite Bay Bio")
    assert granite is not None
    assert granite["amount_gbp"] is None


def test_entries_without_funding_verb_in_title_are_filtered():
    entries = [
        {"title": "Marrowbone Robotics hires a new CFO",
         "summary": "A leadership update, no funding."},
        {"title": "Some headline with no company verb structure",
         "summary": "raises questions about the market"},
        {"title": "Acme Labs raises £2m seed round",
         "summary": "London startup Acme Labs."},
    ]
    names = [item["company_name"]
             for item in rssfeeds._entries_to_items(entries, "Test")]
    # Only the third entry has both a funding verb and a name-before-verb
    # structure in the title.
    assert names == ["Acme Labs"]


def test_proxied_feeds_route_through_the_configured_proxy():
    feeds = rssfeeds.proxied_feeds()
    assert feeds, "expected feeds from sources.yaml"
    template = (config.load_sources().get("feed_proxy") or {}).get("template")
    for feed in feeds:
        # The direct url is always preserved for the local authoritative path.
        assert feed["url"].startswith("http")
        if template:
            # Origin percent-encoded into the proxy so the cloud routine's
            # WebFetch hits a non-blocked IP, not the 403ing origin.
            assert urllib.parse.quote(feed["url"], safe="") in feed["proxied_url"]
        else:
            assert feed["proxied_url"] == feed["url"]
