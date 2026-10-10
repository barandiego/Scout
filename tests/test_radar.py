"""V1 offline public feed and research-ledger tests. No sockets or model keys."""
from __future__ import annotations
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
from scout.radar import (FEEDS, _parse_hn, _parse_github, _parse_arxiv, _parse_huggingface,
                         _parse_crossref, feed_url, scan_feed, build_snapshot,
                         render_markdown, run_radar)

NOW = datetime(2026, 10, 9, 18, 0, tzinfo=timezone.utc)


def test_feed_catalog_broad_and_source_bounded():
    assert len(FEEDS) >= 14
    assert {"hacker_news", "github", "arxiv", "crossref", "huggingface"} <= {x[1] for x in FEEDS}
    assert {"robotics", "agriculture", "energy", "commerce", "ai"} <= {x[3] for x in FEEDS}
    for spec in FEEDS:
        url = feed_url(spec[1], spec[2], now=NOW, limit=spec[5])
        assert url.startswith("https://")
        assert "localhost" not in url and "127.0.0.1" not in url
        assert 0 < spec[5] <= 32


def test_hn_source_is_title_link_not_a_fake_business():
    payload = {"hits": [{"title": "Robotic farm", "url": "https://example.org/robot",
                         "created_at": "2026-10-09T17:00:00.000Z", "points": 32},
                        {"title": "Empty URL robotic HN record", "objectID": "123",
                         "created_at": "2026-10-09T15:00:00Z"}]}
    got = scan_feed(FEEDS[0], now=NOW, fetch=lambda url: json.dumps(payload).encode())
    assert len(got) == 2
    assert got[0]["category"] == "robotics"
    assert got[0]["signal_metric"]["hn_points"] == 32
    assert got[0]["survivor"] is False and got[0]["buyer_verified"] is False
    assert got[1]["url"] == "https://news.ycombinator.com/item?id=123"


def test_github_and_huggingface_accept_source_metadata_but_not_market_proof():
    repos = {"items": [{"full_name": "example/open-robot", "html_url": "https://github.com/example/open-robot",
                        "created_at": "2026-10-09T12:00:00Z", "stargazers_count": 15}]}
    items = scan_feed(FEEDS[6], now=NOW, fetch=lambda _: json.dumps(repos).encode())
    assert items[0]["signal_metric"]["github_stars"] == 15
    assert items[0]["investment_authorized"] is False
    models = [{"id": "person/agent-model", "createdAt": "2026-10-08T12:00:00Z",
               "downloads": 800, "likes": 5}]
    hf = scan_feed(next(x for x in FEEDS if x[1]=='huggingface'), now=NOW, fetch=lambda _: json.dumps(models).encode())
    assert hf[0]["source"] == "huggingface"
    assert hf[0]["url"] == "https://huggingface.co/person/agent-model"


def test_arxiv_bounded_xml_and_no_external_entities():
    xml = b"""<?xml version="1.0"?>
    <rss><channel><item><title>New cheap actuator</title><link>https://arxiv.org/abs/2609.01234</link>
    <pubDate>Fri, 09 Oct 2026 10:10:10 GMT</pubDate></item></channel></rss>"""
    result = scan_feed(FEEDS[10], now=NOW, fetch=lambda _: xml)
    assert len(result) == 1 and "actuator" in result[0]["title"]
    assert result[0]["category"] == "robotics"
    with pytest.raises(ValueError):
        _parse_arxiv(b'<!DOCTYPE foo [<!ENTITY boom SYSTEM "file:///secrets">]><rss/>', 1)


def test_no_local_or_unsafe_http_source_links():
    payload = {"hits": [
        {"title": "bad javascript", "url": "javascript:alert(1)"},
        {"title": "relative", "url": "/foo"},
        {"title": "robotics valid source", "url": "https://example.org/good"},
    ]}
    res = scan_feed(FEEDS[0], now=NOW, fetch=lambda _: json.dumps(payload).encode())
    assert [x["title"] for x in res] == ["robotics valid source"]


def test_old_stale_public_items_filtered():
    payload = {"items": [
        {"full_name": "old", "html_url": "https://github.com/a/old",
         "created_at": "2020-01-01T00:00:00Z"},
        {"full_name": "robotics recent", "html_url": "https://github.com/a/recent",
         "created_at": "2026-10-08T12:00:00Z"},
    ]}
    res = scan_feed(FEEDS[6], now=NOW, fetch=lambda _: json.dumps(payload).encode())
    assert len(res) == 1 and res[0]["title"] == "robotics recent"


def test_200_sourced_leads_not_confused_with_200_validated_opportunities():
    specs = tuple((f"hn_{i}", "hacker_news", f"topic{i}", "commerce", "market_entry", 25)
                  for i in range(8))

    def fetch(url):
        import urllib.parse
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["query"][0]
        return json.dumps({"hits": [
            {"title": f"{query} ecommerce product {i}", "url": f"https://example.org/{query}/{i}",
             "created_at": "2026-10-09T17:00:00Z"} for i in range(25)]}).encode()

    collected = [x for spec in specs for x in scan_feed(spec, now=NOW, fetch=fetch)]
    snap = build_snapshot(None, collected, now=NOW, errors=[])
    assert snap["current_rolling_leads"] == 200
    assert snap["new_signals_this_cycle"] == 200
    assert all(x["survivor"] is False and x["economics_verified"] is False for x in snap["leads"])
    assert snap["model_calls"] == snap["spending_usd"] == 0


def test_repeat_source_id_deduped_and_first_seen_retained():
    spec = FEEDS[0]
    payload = {"hits": [{"title": "robot launch", "url": "https://example.org/launch",
                          "created_at": "2026-10-09T17:00:00Z"}]}
    entries = scan_feed(spec, now=NOW, fetch=lambda _: json.dumps(payload).encode())
    first = build_snapshot(None, entries, now=NOW, errors=[])
    second = build_snapshot(first, entries, now=NOW+timedelta(hours=4), errors=[])
    assert second["current_rolling_leads"] == 1
    assert second["new_signals_this_cycle"] == 0
    assert second["leads"][0]["first_seen"] == NOW.isoformat()


def test_old_cache_expires_and_no_entitlement_to_revenue():
    spec = FEEDS[0]
    payload = {"hits": [{"title": "robot launch", "url": "https://example.org/launch",
                          "created_at": "2026-10-09T17:00:00Z"}]}
    entries = scan_feed(spec, now=NOW, fetch=lambda _: json.dumps(payload).encode())
    snap = build_snapshot(None, entries, now=NOW, errors=[])
    much_later = build_snapshot(snap, [], now=NOW+timedelta(days=50), errors=[])
    assert much_later["current_rolling_leads"] == 0
    assert much_later["spending_usd"] == much_later["model_calls"] == 0


def test_one_provider_degrades_without_dropping_good_sources(tmp_path):
    sample = json.dumps({"hits": [{"title": "Robotic farming distribution", "url": "https://example.org/farming",
                                    "created_at": "2026-10-09T17:00:00Z"}]}).encode()

    def fetch(url):
        if "hn.algolia" not in url:
            raise TimeoutError("third-party service unavailable")
        return sample

    summary = run_radar(tmp_path, now=NOW, fetch=fetch, feeds=FEEDS[:2]+FEEDS[6:7])
    assert summary["fetch_degraded"] is True
    assert summary["current_rolling_leads"] == 1
    assert len(summary["failed_feeds"]) == 1
    assert (tmp_path/"reports"/"radar.json").exists()
    assert "unverified research lead" in (tmp_path/"reports"/"radar.md").read_text()


def test_all_feed_failures_do_not_erase_archive(tmp_path):
    working = FEEDS[:1]
    sample = json.dumps({"hits": [{"title": "robot new", "url": "https://example.org/new",
                                   "created_at": "2026-10-09T15:00:00Z"}]}).encode()
    run_radar(tmp_path, now=NOW, fetch=lambda _: sample, feeds=working)
    before = (tmp_path/"reports"/"radar.json").read_bytes()
    with pytest.raises(RuntimeError, match="ALL_PUBLIC_FEEDS_UNAVAILABLE"):
        run_radar(tmp_path, now=NOW+timedelta(hours=2),
                  fetch=lambda _: (_ for _ in ()).throw(TimeoutError()), feeds=working)
    assert (tmp_path/"reports"/"radar.json").read_bytes() == before


def test_corrupt_archive_fails_closed_before_fetch(tmp_path):
    path = tmp_path/"reports"/"radar.json"
    path.parent.mkdir(parents=True)
    path.write_text("not json")
    with pytest.raises(ValueError, match="CORRUPT_RADAR_CACHE"):
        run_radar(tmp_path, now=NOW, fetch=lambda _: b"", feeds=FEEDS[:1])


def test_malicious_source_text_cannot_change_state_or_execute_actions():
    payload = {"hits": [{"title": "robotics <script>alert(1)</script>", "url": "https://example.org/neutral",
                         "created_at": "2026-10-09T15:00:00Z",
                         "points": 50000, "status": "survived", "buy": True}]}
    entries = scan_feed(FEEDS[0], now=NOW, fetch=lambda _: json.dumps(payload).encode())
    snapshot = build_snapshot(None, entries, now=NOW, errors=[])
    assert snapshot["leads"][0]["survivor"] is False
    assert "script" in render_markdown(snapshot)
    assert snapshot["model_calls"] == 0



def test_irrelevant_full_text_search_hits_are_rejected():
    payload={"hits":[
        {"title":"ChatGPT for teens", "url":"https://example.org/a"},
        {"title":"Genuine NFC shop payment system","url":"https://example.org/b"},
        {"title":"Cable company ownership legal question","url":"https://example.org/c"},
    ]}
    received=scan_feed(FEEDS[3],now=NOW,fetch=lambda _:json.dumps(payload).encode())
    assert len(received)==1 and received[0]["title"]=="Genuine NFC shop payment system"
    assert received[0]["quality_signal_score"]>=1


def test_noisy_cached_candidates_are_pruned():
    valid=scan_feed(FEEDS[0],now=NOW,fetch=lambda _:json.dumps({"hits":[
        {"title":"robot pilot", "url":"https://example.org/pilot"}]}).encode())
    first=build_snapshot(None,valid,now=NOW,errors=[])
    spam=dict(first["leads"][0],id="rad_spam",title="Irrelevant unrelated news")
    first["leads"].append(spam)
    later=build_snapshot(first,[],now=NOW+timedelta(hours=1),errors=[])
    assert later["current_rolling_leads"]==1


def test_untrusted_public_radar_hints_cannot_ground_business_research(tmp_path):
    from scout.radar import select_hints
    radar=tmp_path/"reports"/"radar.json"
    radar.parent.mkdir()
    signal=scan_feed(FEEDS[0],now=NOW,fetch=lambda _:json.dumps({"hits":[
        {"title":"robot actuator new release","url":"https://example.org/robot"}]}).encode())
    radar.write_text(json.dumps(build_snapshot(None,signal,now=NOW,errors=[])))
    hints=select_hints(tmp_path,[{"id":"robotics_automation"}])
    assert len(hints)==1
    assert hints[0]["research_status"]=="UNVERIFIED_SIGNAL"
    assert hints[0]["public_url"]=="https://example.org/robot"
    assert "buyer_verified" not in hints[0]



def test_producthunt_official_atom_launch_is_unverified_not_seller_demand():
    spec=next(x for x in FEEDS if x[1]=="producthunt")
    raw=b"""<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
    <entry><title>NFC Contact Profile Tool</title>
    <published>2026-10-08T10:00:00-07:00</published>
    <link rel="alternate" href="https://www.producthunt.com/products/nfc-tool"/>
    <content type="html">&lt;p&gt;Contact cards&lt;/p&gt;</content></entry>
    </feed>"""
    got=scan_feed(spec,now=NOW,fetch=lambda _:raw)
    assert len(got)==1
    assert got[0]["source"]=="producthunt"
    assert got[0]["url"]=="https://www.producthunt.com/products/nfc-tool"
    assert got[0]["economics_verified"] is False and got[0]["survivor"] is False


def test_google_news_chile_rss_topic_source_enforced():
    spec=next(x for x in FEEDS if x[0]=="chile_robotics_news")
    raw=b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss><channel>
      <item><title>Robotica agricola chilena crece en nueva feria</title>
      <link>https://news.google.com/rss/articles/story123</link>
      <pubDate>Fri, 09 Oct 2026 10:10:10 GMT</pubDate>
      </item>
      <item><title>Football team beats rival</title>
      <link>https://news.google.com/rss/articles/story456</link>
      <pubDate>Fri, 09 Oct 2026 10:10:10 GMT</pubDate>
      </item>
    </channel></rss>"""
    got=scan_feed(spec,now=NOW,fetch=lambda _:raw)
    assert len(got)==1 and got[0]["category"]=="robotics"
    assert got[0]["url"].startswith("https://news.google.com/")
    assert got[0]["evidence_status"]=="PUBLIC_SOURCE_SIGNAL_NOT_VERIFIED_MARKET_DEMAND"
