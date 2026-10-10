"""Offline tests for innovation hypotheses, not invented commercial validation."""
import json
from datetime import datetime, timezone

import pytest
from scout.innovation import PLAYBOOKS, innovation_brief, write_innovation_backlog
from scout.models import Opportunity, RunRecord
from scout.state import Store


NOW="2026-10-09T18:00:00+00:00"


def example(vertical="general", status="watch", name="Robotic agriculture opportunity"):
    return Opportunity(
        opportunity_id="opp_test_"+vertical, discovered_at=NOW, last_updated=NOW,
        name=name, type="physical", vertical=vertical, geography="Chile",
        signal="Commercial products in foreign market",
        what_changed="Technology now available", why_now="Costs changed",
        thesis="A local distributor may capture value by importing supported farming robots",
        value_capture_mechanism="Supplier margin after import financing service and delivery costs",
        participation_path="Validate farm interest and supplier/legal access first",
        evidence_confidence=.65, status=status, real=True, actionable=True,
        unknowns=["Farm users' realistic willingness to pay?"],
        time_horizon="unknown", capital_required="unknown",
    )


def test_innovation_playbook_has_distinct_economic_strategies():
    assert len(PLAYBOOKS) >= 10
    farming=innovation_brief(example("robotics_agritech"))
    ecommerce=innovation_brief(example("ecommerce_niches"))
    investing=innovation_brief(example("asymmetric_investing"))
    assert farming["strategy_hypotheses_not_facts"] != ecommerce["strategy_hypotheses_not_facts"]
    assert investing["strategy_hypotheses_not_facts"] != ecommerce["strategy_hypotheses_not_facts"]
    assert "robots" in json.dumps(farming).lower() or "robotic" in json.dumps(farming).lower()
    assert farming["commercially_validated"] is False
    assert farming["investment_authorized"] is False


def test_existing_market_cannot_be_declared_profitable_without_data():
    b=innovation_brief(example("competitive_positioning"))
    assert b["pricing_confirmed"] is False
    assert b["competition_confirmed"] is False
    assert b["willingness_to_pay_confirmed"] is False
    assert b["capital_required_unverified_estimate"] == "unknown"


def test_no_source_cannot_manufacture_grounding():
    b=innovation_brief(example("chile_localization"))
    assert b["supporting_source_urls"] == []
    assert b["hypothesis_evaluation_questions"] == ["Farm users' realistic willingness to pay?"]


def test_rejected_opportunities_absent_and_watch_not_survived(tmp_path):
    store=Store(tmp_path)
    rec=RunRecord(run_id="test_innovation_backlog",mode="cycle",started_at=NOW,
                  finished_at=NOW,outcome="SUCCESS")
    op=example()
    rejected=example("ecommerce_niches",status="rejected",name="Nonviable idea")
    store.checkpoint(rec,[op,rejected])
    summary=write_innovation_backlog(tmp_path)
    assert summary["research_briefs"] == 1
    result=json.loads((tmp_path/"reports"/"innovation_backlog.json").read_text(encoding="utf-8"))
    assert result["commercially_validated_count"] == 0
    assert result["briefs"][0]["status"] == "watch"
    assert "Nonviable idea" not in (tmp_path/"reports"/"innovation_backlog.md").read_text()


def test_noncanonical_response_rejected():
    with pytest.raises(TypeError):
        innovation_brief({"status":"survived","commercially_validated":True})
