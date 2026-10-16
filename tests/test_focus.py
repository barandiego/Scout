from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from scout.focus import build_focus, render_markdown, saturation_hint, theme, write_focus


def _card(key, title, vertical="open_finance_chile", reviewed=False):
    return {"id": key, "title": title, "vertical": vertical, "status": "watch",
            "critic_reviewed": reviewed, "judge_reviewed": reviewed,
            "discovered_at": "2026-10-15T00:00:00+00:00", "evidence": []}


def _library(cards):
    return {"source": "SCOUT_CANONICAL_PERSISTED_STATE", "generated_at": "2026-10-15T00:00:00+00:00", "cards": cards}


def test_open_finance_aliases_group_for_reporting_but_keep_every_original():
    cards = [_card("a", "Chile Open Finance API conformance"),
             _card("b", "SFA interoperability test harness"),
             _card("c", "Consent-flow testing for Chilean fintechs"),
             _card("n", "NFC review stands", "physical_distribution", reviewed=True)]
    result = build_focus(_library(cards))
    assert result["total_original_cards"] == 4
    assert result["theme_count"] == 2
    assert result["headline_count"] == 2
    assert {x["opportunity_id"] for x in result["headline_candidates"]} == {"a", "n"}
    assert {x["theme"]: set(x["all_opportunity_ids"]) for x in result["themes"]}["chile_open_finance"] == {"a", "b", "c"}
    assert result["buyers_verified"] is False
    assert result["commercial_execution_authorized"] is False


def test_themes_do_not_conflate_distinct_generic_opportunities():
    assert theme(_card("g", "Warehouse robotics efficiency", "general")) != theme(
        _card("h", "Healthcare interoperability", "general"))
    assert theme(_card("n", "NFC review-and-contact displays", "physical_distribution")) == "nfc_products"


def test_concentration_warning_and_review_priority():
    cards = [_card(str(i), f"Open Finance proposal {i}") for i in range(6)]
    cards += [_card("other", "NFC display", "physical_distribution", reviewed=True)]
    result = build_focus(_library(cards))
    assert result["high_concentration"][0] == {"theme": "chile_open_finance", "cards": 6, "share": 0.857}
    assert result["headline_candidates"][0]["opportunity_id"] == "other"
    assert "not a validated buyer" in render_markdown(result)


def test_unknown_or_untrusted_library_fails_closed():
    for library in ({"source": "NOT_CANONICAL", "cards": []},
                    _library([{"title": "x"}]),
                    _library(["bad"]), None):
        with pytest.raises((ValueError, TypeError)):
            build_focus(library)
    with pytest.raises(ValueError):
        build_focus(_library([]), max_headlines=0)


def test_offline_reports_do_not_mutate_library(tmp_path):
    source = _library([_card("x", "SFA consent validation")])
    (tmp_path / "reports").mkdir()
    before = json.dumps(source, sort_keys=True)
    (tmp_path / "reports" / "library.json").write_text(before, encoding="utf-8")
    result = write_focus(tmp_path)
    assert result["headlines"] == 1
    assert (tmp_path / "reports" / "library.json").read_text(encoding="utf-8") == before
    assert json.loads((tmp_path / "reports" / "focus.json").read_text(encoding="utf-8"))["total_original_cards"] == 1


def test_saturation_hint_is_count_only_and_requires_five_records():
    ops = [SimpleNamespace(name=f"SFA private buyer secret {i}", vertical="open_finance_chile", status="watch")
           for i in range(6)]
    hint = saturation_hint(ops)
    assert "chile_open_finance=6" in hint
    assert "private buyer secret" not in hint
    assert "Never invent" in hint
    assert saturation_hint(ops[:4]) == ""
