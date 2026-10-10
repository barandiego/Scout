"""Explicitly staged Scout trial model routing and fail-closed spend envelope.

No startup side effects, paid calls, secrets, or dynamic remote config.
The existing Scout transaction journal is the single accounting authority.
"""
from __future__ import annotations

import math
import os
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

STAGES = ("discovery", "critic", "judge")
ALLOWLIST = {"gpt-6-luna", "gpt-6.1-sol", "gpt-6-astra"}
EFFORTS = {"none", "low", "medium", "high", "xhigh", "max"}
MONEY = ("cycle_usd", "daily_usd", "total_usd",
         "reserve_discovery_usd", "reserve_critic_usd", "reserve_judge_usd")
PRICES = ("input_per_million", "cached_input_per_million", "output_per_million")
PROFILES = ("radar", "deterministic_screening", "triage",
            "discovery", "critic", "judge", "deep_adversary")


class TrialError(ValueError):
    """Sanitised configuration or authority error, never credential content."""


def read_trial(root: Path) -> dict:
    with (root/"config"/"research_trial.yaml").open(encoding="utf-8") as f:
        result = yaml.safe_load(f)
    if not isinstance(result, dict):
        raise TrialError("INVALID_TRIAL_CONFIG")
    return result


def _number(x: object) -> bool:
    return type(x) in (int, float) and math.isfinite(x) and x > 0


def _utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise TrialError("TRIAL_WINDOW_NOT_SET")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise TrialError("INVALID_TRIAL_WINDOW") from None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise TrialError("TRIAL_REQUIRES_UTC")
    return parsed.astimezone(timezone.utc)


def validate_trial(data: dict) -> list[str]:
    errors = []
    try:
        if type(data["enabled"]) is not bool:
            errors.append("TRIAL_ENABLED_MUST_BE_BOOL")
        if data["activation_env"] != "SCOUT_RESEARCH_TRIAL_ARMED":
            errors.append("TRIAL_ACTIVATION_ENV_MISMATCH")
        budget, roles, limits, pricing = (data[k] for k in ("budget", "roles", "limits", "pricing"))
        if any(not _number(budget[k]) for k in MONEY):
            errors.append("INVALID_TRIAL_BUDGET")
        if (_number(budget["daily_usd"]) and _number(budget["total_usd"])
                and (budget["daily_usd"] > 3.0 or budget["total_usd"] > 15.0)):
            errors.append("TRIAL_CEILING_EXCEEDED")
        if _number(budget["cycle_usd"]) and budget["cycle_usd"] > 1.2:
            errors.append("TRIAL_CYCLE_CEILING_EXCEEDED")
        if (_number(budget["cycle_usd"]) and _number(budget["daily_usd"])
                and budget["cycle_usd"] > budget["daily_usd"]):
            errors.append("TRIAL_CYCLE_EXCEEDS_DAY")
        for role in PROFILES:
            r = roles[role]
            if not isinstance(r, dict) or type(r.get("enabled")) is not bool:
                errors.append("INVALID_TRIAL_ROLE")
                continue
            model = r.get("model")
            if role in ("radar", "deterministic_screening"):
                if model != "none" or not r["enabled"]:
                    errors.append("PUBLIC_INGEST_MUST_BE_MODEL_FREE")
            elif model not in ALLOWLIST or r.get("reasoning_effort") not in EFFORTS:
                errors.append("INVALID_TRIAL_MODEL_ROLE")
        if not all(roles[stage]["enabled"] for stage in STAGES):
            errors.append("RESEARCH_STAGES_MUST_BE_ENABLED")
        # Unimplemented roles are deliberately OFF. Prevent silent paid new work.
        if roles["triage"]["enabled"] or roles["deep_adversary"]["enabled"]:
            errors.append("UNIMPLEMENTED_PAID_ROLE_ENABLED")
        # Prevent change to an unexpectedly costly stage/model mix.
        if (roles["discovery"]["model"] != "gpt-6.1-sol"
                or roles["critic"]["model"] != "gpt-6.1-sol"
                or roles["judge"]["model"] != "gpt-6.1-sol"):
            errors.append("UNAPPROVED_MODEL_ROUTING_CHANGE")
        for stage in STAGES:
            if roles[stage]["model"] not in pricing["models"]:
                errors.append("TRIAL_MODEL_PRICING_MISSING")
        if pricing["web_search_per_call"] != 0.01:
            errors.append("TRIAL_WEB_SEARCH_PRICE_CHANGED")
        for model in ALLOWLIST:
            rate = pricing["models"][model]
            if any(not _number(rate[k]) for k in PRICES):
                errors.append("INVALID_TRIAL_PRICING")
        expected = {
            "gpt-6-luna": (0.10, 0.01, 0.50),
            "gpt-6.1-sol": (2.00, 0.10, 10.00),
            "gpt-6-astra": (10.00, 1.00, 50.00),
        }
        for model, rates in expected.items():
            if tuple(pricing["models"][model][k] for k in PRICES) != rates:
                errors.append("TRIAL_PRICING_NEEDS_REAPPROVAL")
        for key in ("lenses_per_cycle", "max_normalized_candidates",
                    "max_candidates_to_critic", "max_candidates_to_judge",
                    "discovery_max_output_tokens", "critic_max_output_tokens",
                    "judge_max_output_tokens", "discovery_max_tool_calls", "critic_max_tool_calls"):
            if type(limits[key]) is not int or limits[key] <= 0:
                errors.append("INVALID_TRIAL_LIMIT")
        if limits["max_normalized_candidates"] > 10:
            errors.append("TRIAL_DISCOVERY_CAP_EXCEEDED")
        if max(limits["max_candidates_to_critic"], limits["max_candidates_to_judge"]) > 1:
            errors.append("TRIAL_REVIEW_CAP_EXCEEDED")
        if (limits["discovery_max_tool_calls"] > 4 or
                limits["critic_max_tool_calls"] > 4 or
                max(limits["discovery_max_output_tokens"], limits["critic_max_output_tokens"]) > 5200
                or limits["judge_max_output_tokens"] > 3600):
            errors.append("TRIAL_CALL_CAP_EXCEEDED")
        # Admission reserves are intentionally conservative for Sol web search
        # but not an absolute statement about provider-side final charges.
        if (budget["reserve_discovery_usd"] < 0.60
                or budget["reserve_critic_usd"] < 0.60
                or budget["reserve_judge_usd"] < 0.40):
            errors.append("TRIAL_RESERVE_INADEQUATE")
        starts = data.get("starts_at_utc")
        ends = data.get("ends_at_utc")
        if starts is None and ends is None and not data["enabled"]:
            pass
        else:
            a, b = _utc(starts), _utc(ends)
            if not timedelta(0) < b-a <= timedelta(days=7):
                errors.append("TRIAL_WINDOW_EXCEEDS_7_DAYS")
    except (KeyError, AttributeError, TypeError, ValueError, OverflowError):
        errors.append("INVALID_TRIAL_STRUCTURE")
    return sorted(set(errors))


def is_armed(data: dict, now: datetime, *, environ: dict | None = None) -> bool:
    if validate_trial(data):
        return False
    if not data["enabled"]:
        return False
    env = os.environ if environ is None else environ
    if env.get(data["activation_env"]) != "1":
        return False
    return _utc(data["starts_at_utc"]) <= now < _utc(data["ends_at_utc"])


def auto_trial_active(root: Path, now: datetime | None = None,
                      *, environ: dict | None = None) -> bool:
    """Scheduled V0 automatically routes to the trial ONLY while doubly armed."""
    now = now or datetime.now(timezone.utc)
    return is_armed(read_trial(root), now, environ=environ)


def budget_window(data: dict, now: datetime) -> tuple[str, str] | None:
    """A signed-off trial window caps ALL Scout AI usage including legacy V0."""
    if (validate_trial(data) or not data["enabled"]):
        return None
    a, b = _utc(data["starts_at_utc"]), _utc(data["ends_at_utc"])
    if a <= now < b:
        return a.isoformat(), b.isoformat()
    return None


def effective_config(base: dict, trial: dict, now: datetime,
                     *, environ: dict | None = None) -> dict:
    if not is_armed(trial, now, environ=environ):
        raise TrialError("TRIAL_NOT_ACTIVATED_OR_OUTSIDE_WINDOW")
    result = deepcopy(base)
    result["budget"] = {k: trial["budget"][k] for k in MONEY if k != "total_usd"}
    result["limits"].update(trial["limits"])
    result["models"] = {s: trial["roles"][s]["model"] for s in STAGES}
    result["reasoning_efforts"] = {s: trial["roles"][s]["reasoning_effort"] for s in STAGES}
    result["pricing"]["web_search_per_call"] = trial["pricing"]["web_search_per_call"]
    result["pricing"]["models"].update(trial["pricing"]["models"])
    result["trial_total_limit_usd"] = trial["budget"]["total_usd"]
    return result


def trial_status(root: Path, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    trial = read_trial(root)
    errors = validate_trial(trial)
    from .state import Store
    store = Store(root)
    ledger = store.runs()
    start = trial.get("starts_at_utc")
    end = trial.get("ends_at_utc")
    trial_runs = []
    if not errors and isinstance(start, str) and isinstance(end, str):
        a, b = _utc(start), _utc(end)
        trial_runs = [r for r in ledger if
                      a <= datetime.fromisoformat(r["started_at"]) < b]
    costs = round(sum(r["cost_usd"] for r in trial_runs), 9)
    uncertain = any(r.get("cost_uncertain") or r.get("pending_stage") for r in trial_runs)
    return {"mode": "STAGED" if not trial["enabled"] else "CONFIGURED",
            "can_incur_spending": is_armed(trial, now),
            "start_utc": start, "end_utc": end,
            "total_limit_usd": trial["budget"]["total_usd"],
            "daily_limit_usd": trial["budget"]["daily_usd"],
            "remaining_estimated_usd": max(0, round(trial["budget"]["total_usd"]-costs, 9)),
            "cost_uncertain": uncertain, "errors": errors,
            "roles": {k: {"model": v["model"], "enabled": v["enabled"]}
                      for k, v in trial["roles"].items()}}
