"""Scout trial: model routing, 7-day cumulative spend, disabled-by-default authority.

No paid API requests or network in this test suite.
"""
from __future__ import annotations

import copy
import json
import shutil
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from scout import pipeline
from scout.models import RunRecord, Usage
from scout.runtime import AIResult
from scout.state import Store
from scout.trial import (TrialError, budget_window, effective_config, is_armed,
                         read_trial, trial_status, validate_trial)

UTC = timezone.utc


def _armed(root, now):
    t = read_trial(root)
    t["enabled"] = True
    t["starts_at_utc"] = (now-timedelta(hours=1)).isoformat()
    t["ends_at_utc"] = (now+timedelta(days=6)).isoformat()
    return t


def test_trial_staged_off_by_default_and_all_roles_explicit():
    t = read_trial(pipeline.ROOT)
    assert validate_trial(t) == []
    assert t["enabled"] is False
    assert t["starts_at_utc"] is None and t["ends_at_utc"] is None
    assert t["budget"]["total_usd"] == 15.0 and t["budget"]["daily_usd"] == 3.0
    assert t["roles"]["discovery"]["model"] == "gpt-6.1-sol"
    assert t["roles"]["critic"]["reasoning_effort"] == "high"
    assert t["roles"]["judge"]["model"] == "gpt-6.1-sol"
    assert t["roles"]["triage"]["model"] == "gpt-6-luna"
    assert t["roles"]["deep_adversary"]["model"] == "gpt-6-astra"
    assert not t["roles"]["deep_adversary"]["enabled"]
    assert not t["roles"]["triage"]["enabled"]


def test_offline_public_model_free():
    data = read_trial(pipeline.ROOT)
    assert data["roles"]["radar"] == {"model": "none", "enabled": True}
    assert data["roles"]["deterministic_screening"] == {"model": "none", "enabled": True}


def test_trial_requires_config_date_and_separate_env_key(monkeypatch):
    now = datetime.now(UTC)
    t = _armed(pipeline.ROOT, now)
    monkeypatch.delenv("SCOUT_RESEARCH_TRIAL_ARMED", raising=False)
    assert is_armed(t, now) is False
    assert is_armed(t, now, environ={"SCOUT_RESEARCH_TRIAL_ARMED": "1"})
    assert not is_armed(t, now+timedelta(days=8),
                        environ={"SCOUT_RESEARCH_TRIAL_ARMED": "1"})


def test_trial_window_cannot_be_backfilled_extended_or_timezone_shifted():
    now = datetime.now(UTC)
    data = _armed(pipeline.ROOT, now)
    data["ends_at_utc"] = (now+timedelta(days=8)).isoformat()
    assert "TRIAL_WINDOW_EXCEEDS_7_DAYS" in validate_trial(data)
    data = _armed(pipeline.ROOT, now)
    data["starts_at_utc"] = "2026-10-10T12:00:00-03:00"
    assert "INVALID_TRIAL_STRUCTURE" in validate_trial(data)


@pytest.mark.parametrize("field,value", [
    ("total_usd", 15.00001),
    ("daily_usd", 3.00001),
    ("cycle_usd", 1.20001),
    ("reserve_discovery_usd", .001),
])
def test_trial_spend_envelope_cannot_be_increased_or_reserves_lowered(field, value):
    data = read_trial(pipeline.ROOT)
    data["budget"][field] = value
    assert validate_trial(data)


def test_arbitrary_or_unpriced_model_and_unimplemented_roles_rejected():
    data = read_trial(pipeline.ROOT)
    data["roles"]["discovery"]["model"] = "user-designed-unknown"
    assert validate_trial(data)
    data = read_trial(pipeline.ROOT)
    data["roles"]["deep_adversary"]["enabled"] = True
    assert "UNIMPLEMENTED_PAID_ROLE_ENABLED" in validate_trial(data)
    data = read_trial(pipeline.ROOT)
    data["pricing"]["models"]["gpt-6.1-sol"]["output_per_million"] = .1
    assert "TRIAL_PRICING_NEEDS_REAPPROVAL" in validate_trial(data)


def test_role_output_is_explicit_and_does_not_touch_v0_base(monkeypatch):
    data = read_trial(pipeline.ROOT)
    before = copy.deepcopy(pipeline.load_yaml(pipeline.ROOT/"config"/"scout.yaml"))
    with pytest.raises(TrialError):
        effective_config(before, data, datetime.now(UTC),
                         environ={"SCOUT_RESEARCH_TRIAL_ARMED": "1"})
    data = _armed(pipeline.ROOT, datetime.now(UTC))
    effective = effective_config(before, data, datetime.now(UTC),
                                 environ={"SCOUT_RESEARCH_TRIAL_ARMED": "1"})
    assert effective["models"] == {s:"gpt-6.1-sol" for s in ("discovery","critic","judge")}
    assert effective["reasoning_efforts"] == {"discovery":"medium","critic":"high","judge":"medium"}
    assert effective["budget"]["daily_usd"] == 3.0
    assert effective["trial_total_limit_usd"] == 15.0
    assert before["budget"]["daily_usd"] == .5
    assert before["models"]["discovery"] == "gpt-5.6-luna"


def test_budget_total_counts_existing_v0_and_trial_usage():
    budget = pipeline.Budget(1.2, 3.0, prior_daily=.4,
                             total_limit=15, prior_total=14.62)
    assert budget.can_spend(.40) is False
    assert budget.can_spend(.35) is True
    budget.add(Usage(model="fake", estimated_cost_usd=.25))
    assert budget.can_spend(.15) is False
    assert budget.remaining() == pytest.approx(.13)


def test_overflow_or_uncertain_model_usage_blocks_future_requests():
    b = pipeline.Budget(1.2, 3.0, prior_daily=2.95,
                        total_limit=15, prior_total=13.5)
    assert not b.can_spend(.60)
    b = pipeline.Budget(1.2, 3.0, total_limit=15, prior_total=5)
    b.add(Usage(model="fake", estimated_cost_usd=.04, available=False))
    assert not b.can_spend(.01)


def test_staged_cli_status_requires_no_key_or_live_provider(tmp_path):
    shutil.copytree(pipeline.ROOT/"config", tmp_path/"config")
    status = trial_status(tmp_path)
    assert status["mode"] == "STAGED"
    assert status["can_incur_spending"] is False
    assert status["remaining_estimated_usd"] == 15.0


def test_not_armed_trial_never_calls_model_or_writes_spending(tmp_path, monkeypatch):
    shutil.copytree(pipeline.ROOT/"config", tmp_path/"config")
    monkeypatch.setattr(pipeline, "ROOT", tmp_path)
    monkeypatch.setattr(pipeline, "AIClient", lambda *_: (_ for _ in ()).throw(
        AssertionError("Model must not be contacted without authority")))
    output = pipeline._run_cycle(trial=True)
    assert not output.ok and output.outcome == "FAILED_INFRASTRUCTURE"
    assert not Store(tmp_path).runs()


def test_real_pipeline_trial_route_uses_sol_with_explicit_efforts(tmp_path, monkeypatch):
    now = datetime.now(UTC)
    shutil.copytree(pipeline.ROOT/"config", tmp_path/"config")
    t = _armed(tmp_path, now)
    (tmp_path/"config"/"research_trial.yaml").write_text(yaml.safe_dump(t), encoding="utf-8")
    monkeypatch.setenv("SCOUT_RESEARCH_TRIAL_ARMED", "1")
    monkeypatch.setattr(pipeline, "ROOT", tmp_path)
    from scout.runtime import AIResult
    from scout.models import Usage
    good = {
        "title":"Robot service in Chile",
        "type":"physical", "vertical":"robotics_agritech",
        "geography":"Chile", "observed_change":"An actual product released",
        "economic_implication":"The equipment may create a viable distributor role",
        "value_capture":"Hardware distribution margin after delivery and service",
        "participation_path":"Obtain suppliers, validate customers and warranty economics",
        "discovery_lens":"adoption_lag", "evidence_confidence":.7,
        "real":True,"actionable":True,
        "evidence":[{"title":"Source","url":"https://primary.example/product",
                     "claim":"Product release","source_type":"primary"},
                    {"title":"Second","url":"https://secondary.example/industry",
                     "claim":"Independent industry context","source_type":"independent"}],
    }
    seen=[]
    class Fake:
        def json_research(self, **kwargs):
            model=kwargs["model"];effort=kwargs["reasoning_effort"]
            seen.append((model,effort,kwargs["max_tool_calls"],kwargs["max_output_tokens"]))
            kind=("discovery" if "Scout Discovery" in kwargs["instructions"]
                  else "critic" if "adversarial" in kwargs["instructions"] else "judge")
            data={
                "discovery":{"candidates":[good]},
                "critic":{"fatal":False,"critic_case":"Potentially feasible with unknown buyer demand",
                          "contrary_evidence":[],"unknowns":["Buyer not confirmed"],
                          "falsification_conditions":["Interview operator"],"evidence_confidence":.7},
                "judge":{"status":"watch","vertical_fatal":False,
                         "decision_reason":"Missing commercial proof",
                         "judgment_confidence":.7,"major_risks":[],"unknowns":[]},
            }[kind]
            return AIResult(data, Usage(model=model,estimated_cost_usd=.02),
                            {"https://primary.example/product","https://secondary.example/industry"})
    monkeypatch.setattr(pipeline, "AIClient", lambda *_: Fake())
    run=pipeline._run_cycle(trial=True)
    assert run.ok and run.mode == "trial_cycle"
    assert [x[0] for x in seen]==["gpt-6.1-sol"]*3
    assert [x[1] for x in seen]==["medium","high","medium"]
    assert run.cost_usd == pytest.approx(.06)
    assert len(Store(tmp_path).opportunities()) == 1
    assert all(x.status != "survived" for x in Store(tmp_path).opportunities())


def test_global_seven_day_usage_blocks_new_calls_even_on_new_day(tmp_path,monkeypatch):
    now = datetime.now(UTC)
    shutil.copytree(pipeline.ROOT/"config", tmp_path/"config")
    trial=_armed(tmp_path,now)
    trial["starts_at_utc"]=(now-timedelta(days=4)).isoformat()
    trial["ends_at_utc"]=(now+timedelta(days=3)).isoformat()
    (tmp_path/"config"/"research_trial.yaml").write_text(yaml.safe_dump(trial))
    monkeypatch.setenv("SCOUT_RESEARCH_TRIAL_ARMED", "1")
    monkeypatch.setattr(pipeline, "ROOT", tmp_path)
    # The account has previous V0 usage from two UTC days ago; the daily
    # budget has room, but the combined SEVEN DAY cap has only $0.30.
    past = (now-timedelta(days=2)).isoformat()
    before=RunRecord(run_id="previous_project_spend",mode="cycle",
                     started_at=past,finished_at=past,ok=True,
                     outcome="SUCCESS",cost_usd=14.7)
    Store(tmp_path).checkpoint(before, [])
    monkeypatch.setattr(pipeline,"AIClient",lambda *_: (_ for _ in ()).throw(
        AssertionError("No paid work once project trial envelope exhausted")))
    result=pipeline._run_cycle(trial=True)
    assert result.budget_exhausted and result.outcome=="BUDGET_STOP"
    assert result.usages == []



def test_scheduled_cycle_auto_switches_only_with_two_factor_trial_gate():
    from scout.trial import auto_trial_active
    now=datetime.now(UTC)
    assert auto_trial_active(pipeline.ROOT,now,environ={"SCOUT_RESEARCH_TRIAL_ARMED":"1"}) is False


def test_trial_auto_active_respects_end_and_unarmed_flag(tmp_path):
    from scout.trial import auto_trial_active
    now=datetime.now(UTC)
    shutil.copytree(pipeline.ROOT/"config",tmp_path/"config")
    settings=_armed(tmp_path,now)
    (tmp_path/"config"/"research_trial.yaml").write_text(yaml.safe_dump(settings))
    assert auto_trial_active(tmp_path,now,environ={"SCOUT_RESEARCH_TRIAL_ARMED":"1"})
    assert not auto_trial_active(tmp_path,now+timedelta(days=7),
                                 environ={"SCOUT_RESEARCH_TRIAL_ARMED":"1"})
    assert not auto_trial_active(tmp_path,now,environ={})



def test_model_check_is_runnable_without_trial_arming_or_paid_generation(monkeypatch,capsys):
    import sys
    from scout import cli
    calls=[]
    class Fake:
        def __init__(self, pricing):
            assert "gpt-6.1-sol" in pricing["models"]
        def validate_models(self, models):
            calls.append(models)
    monkeypatch.setattr(cli, "AIClient", Fake)
    monkeypatch.setattr(sys, "argv", ["scout.cli", "trial-model-check"])
    cli.main()
    out=json.loads(capsys.readouterr().out)
    assert out["ok"] and out["inference_calls"] == 0
    assert out["model_list_checked"] == ["gpt-6.1-sol"]
    assert calls == [["gpt-6.1-sol"]]


def test_trial_cap_prevents_model_spend_even_when_utc_day_changed(tmp_path,monkeypatch):
    now=datetime.now(UTC)
    shutil.copytree(pipeline.ROOT/"config", tmp_path/"config")
    trial=_armed(tmp_path,now)
    trial["starts_at_utc"]=(now-timedelta(days=4)).isoformat()
    trial["ends_at_utc"]=(now+timedelta(days=3)).isoformat()
    (tmp_path/"config"/"research_trial.yaml").write_text(yaml.safe_dump(trial))
    monkeypatch.setenv("SCOUT_RESEARCH_TRIAL_ARMED","1")
    monkeypatch.setattr(pipeline,"ROOT",tmp_path)
    at=(now-timedelta(days=2)).isoformat()
    previous=RunRecord(run_id="old_cycle",mode="cycle",started_at=at,
                       finished_at=at,ok=True,outcome="SUCCESS",cost_usd=14.8)
    Store(tmp_path).checkpoint(previous, [])
    monkeypatch.setattr(pipeline,"AIClient",lambda *_: (_ for _ in ()).throw(
        AssertionError("No AI request while global 7day spend close to cap")))
    result=pipeline._run_cycle(trial=True)
    assert result.outcome=="BUDGET_STOP"
    assert result.budget_remaining_usd <= .2+1e-6
    assert result.usages==[]
