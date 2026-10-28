import json
from datetime import datetime, timezone
import pytest

from scout.procurement_completion import CompletionError, validate_completion
from scout.procurement_io import ProcurementStore

@pytest.fixture
def env(tmp_path):
    marker = tmp_path / "pending.json"
    report = tmp_path / "fresh.json"
    state = tmp_path / "events.jsonl"
    marker.write_text(json.dumps({"schema": 1, "run_id": "42"}), encoding="utf-8")
    def write(outcome="DEGRADED_INCOMPLETE_SOURCE_WINDOW", ok=False, failures=None):
        report.write_text(json.dumps({"generated_at": "2026-10-28T10:00:01Z",
            "outcome": outcome, "ok": ok, "diagnostics": {"api_failures": failures or {}, "detail_cap_exhausted": outcome == "DEGRADED_INCOMPLETE_SOURCE_WINDOW"}}),
            encoding="utf-8")
    write()
    def check(code=2, run_id="42"):
        return validate_completion(marker=marker, report=report, state=state,
            run_id=run_id, exit_code=code,
            started_at=datetime(2026, 10, 28, 10, 0, tzinfo=timezone.utc))
    return marker, report, state, write, check

def test_degraded_normal_completion_is_evidence_not_success(env):
    marker, report, state, write, check = env
    receipt = check()
    assert receipt["exit_code"] == 2
    assert receipt["report_sha256"] and receipt["state_sha256"] is None
    assert marker.exists() and report.exists()

def test_uncontrolled_or_stale_or_mismatched_completion_blocks(env):
    marker, report, state, write, check = env
    with pytest.raises(CompletionError): check(run_id="43")
    with pytest.raises(CompletionError): check(code=1)
    write("COMPLETE", True)
    with pytest.raises(CompletionError): check(code=2)
    assert check(code=0)["run_id"] == "42"
    data = json.loads(report.read_text(encoding="utf-8"))
    data["generated_at"] = "2026-10-27T10:00:00Z"
    report.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(CompletionError, match="stale_report"): check(code=0)

def test_rate_limit_requires_durably_recorded_active_cooldown(env):
    marker, report, state, write, check = env
    write("DEGRADED_API_ERRORS", False, {"api_rate_limited": 1})
    with pytest.raises(CompletionError, match="cooldown_missing"): check()
    ProcurementStore(state).set_rate_limit_cooldown("2026-10-28T09:00:00Z")
    with pytest.raises(CompletionError, match="cooldown_not_active"): check()
    ProcurementStore(state).set_rate_limit_cooldown("2026-10-29T12:00:00Z")
    receipt = check()
    assert receipt["state_sha256"] and marker.exists()

def test_unknown_outcome_and_malformed_state_fail_closed(env):
    marker, report, state, write, check = env
    write("SURPRISE", False)
    with pytest.raises(CompletionError): check()
    write("DEGRADED_QUOTA_COOLDOWN", False)
    state.write_text("{invalid", encoding="utf-8")
    with pytest.raises((CompletionError, ValueError)): check()
