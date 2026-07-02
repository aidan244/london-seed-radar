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


def test_colloquial_uk_press_verbs_are_triaged():
    # regression: 'bags', 'scoops', 'pockets', 'grabs', 'snags' headlines
    # were silently dropped before name extraction ever ran
    entries = [
        {"title": "Acme Labs bags £2m to build lab tools",
         "summary": "London seed round."},
        {"title": "Brixton Bio scoops £1.5m pre-seed",
         "summary": "South London biotech."},
        {"title": "Camden AI pockets £3m seed",
         "summary": "AI startup in Camden."},
        {"title": "Dalston Data grabs £4m", "summary": "seed round"},
        {"title": "Exmoor Energy snags £900k pre-seed",
         "summary": "climate tech."},
    ]
    names = [item["company_name"]
             for item in rssfeeds._entries_to_items(entries, "Test")]
    assert names == ["Acme Labs", "Brixton Bio", "Camden AI",
                     "Dalston Data", "Exmoor Energy"]


def test_headline_fragments_are_not_company_names():
    # regression: the live DB accumulated rows like "UK fintech's
    # stablecoin clash with the" and "VivaTech: A Record 10th Edition
    # Comes to a" because everything before a funding verb became a name
    entries = [
        {"title": "UK fintech's stablecoin clash with the raises questions",
         "summary": "an opinion piece, seed funding mentioned"},
        {"title": "VivaTech: A Record 10th Edition Comes to a closes big",
         "summary": "conference wrap, investment roundup"},
        {"title": "Exclusive: Acme Labs raises £2m seed round",
         "summary": "London startup Acme Labs."},
        {"title": "Meet the team behind Acme as it raises questions",
         "summary": "profile piece about funding"},
    ]
    items = rssfeeds._entries_to_items(entries, "Test")
    names = [item["company_name"] for item in items]
    # the fragments are skipped; the Exclusive: prefix is stripped from a
    # real name rather than kept
    assert names == ["Acme Labs"]


def test_plausible_company_name_keeps_odd_real_names():
    assert rssfeeds._plausible_company_name("Record OS")
    assert rssfeeds._plausible_company_name("01Health")
    assert rssfeeds._plausible_company_name("Marks & Spencer Ventures")
    assert not rssfeeds._plausible_company_name("UK Finance and")
    assert not rssfeeds._plausible_company_name("")
    assert not rssfeeds._plausible_company_name(
        "A very long headline fragment that keeps going and going forever")


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
