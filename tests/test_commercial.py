"""Scout's first-dollar queue triages existing research; it never invents sales."""
import json
from datetime import datetime, timezone

import pytest

from scout.commercial import commercial_review_queue, render_commercial_queue, write_commercial_queue


def card(name="NFC product kit", vertical="chile_localization", *,
         buyer_unverified=True, grounded=3):
    return {
        "id": "id-" + name.casefold().replace(" ", "-"),
        "title": name, "vertical": vertical, "geography": "Chile",
        "status": "watch", "research_status": "WATCH_REQUIRES_VALIDATION",
        "participation_path": "Compare products and verify a buyer first",
        "critic_reviewed": True, "judge_reviewed": True,
        "authorized_for_execution": False,
        "verified_sales": None,
        "evidence": [
            {"title": "Evidence", "url": f"https://source.example/{i}",
             "source_type": "primary", "grounded_in_provider_search": True}
            for i in range(grounded)
        ],
    }


def library(*cards):
    return {
        "source": "SCOUT_CANONICAL_PERSISTED_STATE",
        "generated_at": datetime(2026, 10, 10, tzinfo=timezone.utc).isoformat(),
        "cards": list(cards),
    }


def test_only_specific_source_backed_reviewed_niches_selected():
    items = [
        card("NFC review kit"),
        card("Chile SFA conformance test", "open_finance_chile"),
        card("Chile open finance sector expansion", "open_finance_chile"),
        card("Battery storage growth", "general"),
        card("NFC test unsupported", grounded=1),
        card("Securities investment kit", "public_markets"),
    ]
    report = commercial_review_queue(library(*items))
    assert len(report["selected"]) == 2
    assert [c["vertical"] for c in report["selected"]] == [
        "chile_localization", "open_finance_chile"
    ]
    assert report["buyer_qualified_count"] == 0
    assert report["revenue_usd_verified"] is None
    assert all(c["automatic_outreach_authorized"] is False for c in report["selected"])
    assert all(c["economic_status"] == "UNVALIDATED_NO_VERIFIED_BUYER_OR_SALE"
               for c in report["selected"])
    assert all("actual_third_party_receipt" in c["missing_to_prove"] for c in report["selected"])


def test_unreviewed_specific_product_can_be_researched_but_never_promoted():
    bad = card("NFC product kit")
    bad["critic_reviewed"] = False
    selected = commercial_review_queue(library(bad))["selected"]
    assert len(selected) == 1
    assert selected[0]["independent_review_status"] == "REVIEW_PENDING_DO_NOT_PROMOTE"
    assert "independent_critic_and_judge" in selected[0]["missing_to_prove"]
    assert not selected[0]["buyer_verified"]
    assert not selected[0]["automatic_outreach_authorized"]
    bad["critic_reviewed"] = True
    bad["participation_path"] = ""
    assert commercial_review_queue(library(bad))["selected"] == []
    bad["participation_path"] = "Make something"
    bad["status"] = "rejected"
    assert commercial_review_queue(library(bad))["selected"] == []


def test_input_is_required_to_be_canonical_and_restricted():
    with pytest.raises(ValueError, match="CANONICAL_SCOUT_LIBRARY_REQUIRED"):
        commercial_review_queue({"cards": [card()]})
    with pytest.raises(ValueError, match="INVALID_COMMERCIAL_REVIEW_SIZE"):
        commercial_review_queue(library(card()), maximum=0)


def test_source_text_cannot_inject_html_into_markdown():
    bad = card("NFC product kit <script>steal()</script> | foo [bad]")
    bad["participation_path"] = "<script>steal()</script>"
    result = render_commercial_queue(commercial_review_queue(library(bad)))
    assert "<script>" not in result
    assert "›" in result
    assert "Zero verified buyers" in result


def test_offline_report_writes_without_new_research_or_customer_claim(tmp_path):
    (tmp_path / "reports").mkdir()
    report = write_commercial_queue(
        tmp_path, library(card("Chile NFC test kit"), card("Generic macro", "general"))
    )
    data = json.loads((tmp_path / "reports" / "commercial_queue.json").read_text())
    assert report["research_queue_count"] == 1
    assert data["first_dollar_verified"] is False
    assert data["buyer_qualified_count"] == 0
    assert "WATCH" in (tmp_path / "reports" / "commercial_queue.md").read_text()


def test_realistic_chile_niche_queue_excludes_generic_finance_macro():
    finance_macro = card(
        "Chile’s Open Finance implementation is moving toward interoperable production infrastructure",
        "open_finance_chile",
    )
    specific = [
        card("Narrow Chilean e-commerce returns-recovery test", "ecommerce_niches"),
        card("NFC review-conversion kits for Chilean cafés", "chile_localization"),
        card("Open-finance conformance test asset for Chilean participants", "open_finance_chile"),
        card("BESS and inverter compliance pre-check in Chile", "energy_infrastructure"),
        card("Indoor-farm lighting audit wedge", "robotics_agritech"),
    ]
    for c in specific:
        c["critic_reviewed"] = c["judge_reviewed"] = False
    report = commercial_review_queue(library(finance_macro, *specific))
    assert [x["vertical"] for x in report["selected"]] == [
        "ecommerce_niches", "chile_localization", "open_finance_chile", "energy_infrastructure"
    ]
    assert all(x["independent_review_status"] == "REVIEW_PENDING_DO_NOT_PROMOTE"
               for x in report["selected"])
    assert all("independent_critic_and_judge" in x["missing_to_prove"] for x in report["selected"])
    assert not any("interoperable production infrastructure" in x["title"] for x in report["selected"])
