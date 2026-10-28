"""Offline prototype: validate a fresh, controlled monitor completion.

This does not publish state, remove a pending marker, start a monitor, or
establish safe cross-host coordination.
"""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from .procurement_io import ProcurementStore
from .procurement_chile import monitor_health
from .procurement_core import ProcurementDataError
from .state import StateError

class CompletionError(ValueError):
    pass

def _digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

def validate_completion(*, marker: Path, report: Path, state: Path,
                        run_id: str, exit_code: int, started_at: datetime) -> dict:
    """Validate fresh, unique-report evidence; never mutate any state.

    Caller must ensure report path was absent before starting this invocation,
    and must bind and atomically persist state/report/marker removal separately.
    """
    if not isinstance(run_id, str) or not run_id.isdecimal():
        raise CompletionError("invalid_run_id")
    if started_at.tzinfo is None:
        raise CompletionError("invalid_start_time")
    try:
        pending = json.loads(marker.read_text(encoding="utf-8"))
        value = json.loads(report.read_text(encoding="utf-8"))
        if pending != {"schema": 1, "run_id": run_id} or not isinstance(value, dict):
            raise CompletionError("marker_or_report_invalid")
        generated = datetime.fromisoformat(value["generated_at"].replace("Z", "+00:00"))
        if generated.tzinfo is None or generated < started_at.astimezone(timezone.utc).replace(microsecond=0):
            raise CompletionError("stale_report")
        ok, outcome, diag = value["ok"], value["outcome"], value["diagnostics"]
        if type(ok) is not bool or not isinstance(outcome, str) or not isinstance(diag, dict):
            raise CompletionError("invalid_report")
        if exit_code == 0:
            if not ok or outcome != "COMPLETE":
                raise CompletionError("inconsistent_status")
        elif exit_code == 2:
            if ok or outcome not in {"DEGRADED_API_ERRORS", "DEGRADED_TRANSIENT_API", "DEGRADED_QUOTA_COOLDOWN",
                                     "DEGRADED_INCOMPLETE_REQUEST_BUDGET", "DEGRADED_MALFORMED_DETAIL",
                                     "DEGRADED_INCOMPLETE_SOURCE_WINDOW"}:
                raise CompletionError("inconsistent_status")
        else:
            raise CompletionError("unknown_exit")
        failures = diag.get("api_failures")
        if not isinstance(failures, dict):
            raise CompletionError("invalid_diagnostics")
        if outcome not in {"DEGRADED_TRANSIENT_API", "DEGRADED_QUOTA_COOLDOWN"}:
            if monitor_health(diag) != (ok, outcome):
                raise CompletionError("diagnostics_outcome_mismatch")
        elif outcome == "DEGRADED_TRANSIENT_API" and not failures:
            raise CompletionError("transient_failure_missing")
        store = ProcurementStore(state)
        if failures.get("api_rate_limited") or outcome == "DEGRADED_QUOTA_COOLDOWN":
            cooldown = store.latest_rate_limit_cooldown()
            if not cooldown:
                raise CompletionError("cooldown_missing")
            until = datetime.fromisoformat(cooldown.replace("Z", "+00:00"))
            if until.tzinfo is None or until <= generated:
                raise CompletionError("cooldown_not_active")
    except CompletionError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError, StateError, ProcurementDataError):
        raise CompletionError("completion_unverifiable") from None
    return {"schema": 1, "run_id": run_id, "report_sha256": _digest(report),
            "state_sha256": _digest(state), "exit_code": exit_code}
