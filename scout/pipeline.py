from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

from .models import EvidenceItem, Opportunity, RunRecord, Usage
from .runtime import AIClient

ROOT = Path(__file__).resolve().parents[1]


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def append_jsonl(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def canonical_text(op: Opportunity) -> str:
    raw = " ".join([op.name, op.type, op.vertical, op.geography, op.thesis]).lower()
    return re.sub(r"[^a-z0-9]+", " ", raw).strip()


def fingerprint(op: Opportunity) -> str:
    return hashlib.sha256(canonical_text(op).encode()).hexdigest()[:20]


def token_set(text: str) -> set[str]:
    return {x for x in text.split() if len(x) > 2}


def similarity(a: Opportunity, b: Opportunity) -> float:
    sa, sb = token_set(canonical_text(a)), token_set(canonical_text(b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def is_duplicate(op: Opportunity, stored: Iterable[Opportunity], threshold: float) -> bool:
    fp = fingerprint(op)
    for old in stored:
        same = fingerprint(old) == fp or similarity(op, old) >= threshold
        if not same:
            continue
        if op.material_update and op.opportunity_id == old.opportunity_id:
            old_urls = {e.url for e in old.evidence}
            new_urls = {e.url for e in op.evidence} - old_urls
            if new_urls and len(op.update_summary.strip()) >= 20:
                return False
        return True
    return False


def hard_gate_reasons(op: Opportunity) -> list[str]:
    reasons = []
    if not op.real:
        reasons.append("underlying_not_verified_real")
    if len(op.evidence) < 2:
        reasons.append("insufficient_evidence")
    if not any(e.url.startswith("http") for e in op.evidence):
        reasons.append("no_citable_source")
    if op.evidence_confidence < 0.55:
        reasons.append("low_evidence_confidence")
    if len(op.value_capture_mechanism.strip()) < 20:
        reasons.append("no_plausible_value_capture")
    if not op.actionable:
        reasons.append("not_actionable")
    if len(op.participation_path.strip()) < 10:
        reasons.append("no_realistic_participation_path")
    return reasons


class Budget:
    def __init__(self, cycle_limit: float, daily_limit: float, prior_daily: float = 0.0):
        self.cycle_limit = cycle_limit
        self.daily_limit = daily_limit
        self.prior_daily = prior_daily
        self.cycle = 0.0

    def can_spend(self, reserve: float = 0.0) -> bool:
        return (
            self.cycle + reserve <= self.cycle_limit
            and self.prior_daily + self.cycle + reserve <= self.daily_limit
        )

    def add(self, usage: Usage) -> None:
        self.cycle += usage.estimated_cost_usd


def normalize_candidate(raw: dict[str, Any]) -> Opportunity:
    now = utcnow()
    evidence = [EvidenceItem.model_validate(x) for x in raw.get("evidence", [])]
    primary = [e.url for e in evidence if e.source_type == "primary"]
    independent = [e.url for e in evidence if e.source_type == "independent"]
    key = f"{raw.get('name','')}|{raw.get('vertical','general')}|{raw.get('geography','global')}"
    oid = "opp_" + hashlib.sha1(key.lower().encode()).hexdigest()[:12]
    return Opportunity(
        opportunity_id=oid,
        discovered_at=now,
        last_updated=now,
        name=str(raw.get("name", "Unnamed opportunity")),
        type=str(raw.get("type", "unknown")),
        vertical=str(raw.get("vertical", "general")),
        geography=str(raw.get("geography", "global")),
        signal=str(raw.get("signal", "")),
        what_changed=str(raw.get("what_changed", "")),
        why_now=str(raw.get("why_now", "")),
        thesis=str(raw.get("thesis", "")),
        value_capture_mechanism=str(raw.get("value_capture_mechanism", "")),
        evidence=evidence,
        primary_sources=primary,
        independent_sources=independent,
        contrary_evidence=list(raw.get("contrary_evidence", [])),
        evidence_confidence=float(raw.get("evidence_confidence", 0)),
        capital_required=str(raw.get("capital_required", "unknown")),
        diego_hours_initial=str(raw.get("diego_hours_initial", "unknown")),
        diego_hours_ongoing=str(raw.get("diego_hours_ongoing", "unknown")),
        ai_leverage=str(raw.get("ai_leverage", "unknown")),
        time_horizon=str(raw.get("time_horizon", "unknown")),
        major_risks=list(raw.get("major_risks", [])),
        unknowns=list(raw.get("unknowns", [])),
        falsification_conditions=list(raw.get("falsification_conditions", [])),
        real=bool(raw.get("real", False)),
        actionable=bool(raw.get("actionable", False)),
        participation_path=str(raw.get("participation_path", "")),
        material_update=bool(raw.get("material_update", False)),
        update_summary=str(raw.get("update_summary", "")),
    )


def _vertical_config(vertical: str) -> dict[str, Any]:
    path = ROOT / "config" / "verticals" / f"{vertical}.yaml"
    if not path.exists():
        path = ROOT / "config" / "verticals" / "general.yaml"
    return load_yaml(path)


def discover(ai: AIClient, cfg: dict[str, Any], lenses: list[dict[str, Any]], budget: Budget) -> tuple[list[Opportunity], list[Usage]]:
    model = cfg["models"]["discovery"]
    results: list[Opportunity] = []
    usages: list[Usage] = []
    reserve = float(cfg["budget"]["reserve_discovery_usd"])
    for batch in [lenses]:
        if not batch or not budget.can_spend(reserve):
            break
        prompt = f"""Research current and still-live economic signals for these independent discovery lenses:\n{json.dumps(batch, ensure_ascii=False)}\n\nReturn ONLY JSON with shape {{\"candidates\":[...]}}. Generate hypotheses from observed evidence, never free-floating ideas. Each candidate must include: name,type,vertical,geography,signal,what_changed,why_now,thesis,value_capture_mechanism,evidence (2-4 items with title,url,source_type primary|independent|other,claim), contrary_evidence,evidence_confidence 0..1,capital_required,diego_hours_initial,diego_hours_ongoing,ai_leverage,time_horizon,major_risks,unknowns,falsification_conditions,real,actionable,participation_path,material_update,update_summary. Set material_update true only when this is a previously-known opportunity with genuinely thesis-changing new evidence. Prefer primary/current sources and independently verify material claims. It is acceptable to return zero candidates."""
        res = ai.json_research(
            model=model,
            instructions="You are Scout Discovery. Maximize useful recall but remain evidence-led. Do not defend ideas; later stages will criticize them. Never invent companies, assets, data, regulation, demand, customers or news.",
            prompt=prompt,
            max_output_tokens=cfg["limits"]["discovery_max_output_tokens"],
            web_search=True,
            max_tool_calls=int(cfg["limits"]["discovery_max_tool_calls"]),
            reasoning_effort="low",
        )
        budget.add(res.usage); usages.append(res.usage)
        for raw in res.data.get("candidates", []):
            try:
                results.append(normalize_candidate(raw))
            except Exception:
                continue
        if len(results) >= cfg["limits"]["max_normalized_candidates"]:
            break
    return results[: cfg["limits"]["max_normalized_candidates"]], usages


def critic(ai: AIClient, cfg: dict[str, Any], op: Opportunity, budget: Budget) -> tuple[Opportunity, Usage | None]:
    reserve = float(cfg["budget"]["reserve_critic_usd"])
    if not budget.can_spend(reserve):
        return op, None
    model = cfg["models"]["critic"]
    prompt = f"""Attack this opportunity. Search specifically for fatal contrary evidence, incumbents, saturation, bad unit economics, regulation, technical infeasibility, valuation already pricing the thesis, dilution, access/liquidity, substitutes, hidden capital, or bad timing.\n\nOPPORTUNITY:\n{op.model_dump_json(indent=2)}\n\nReturn ONLY JSON: {{\"fatal\":bool,\"critic_case\":str,\"contrary_evidence\":[str],\"unknowns\":[str],\"falsification_conditions\":[str],\"evidence_confidence\":0..1}}. A kill is a successful outcome."""
    res = ai.json_research(
        model=model,
        instructions="You are an adversarial investment/business critic. Your job is to kill weak opportunities, not preserve them.",
        prompt=prompt,
        max_output_tokens=cfg["limits"]["critic_max_output_tokens"],
        web_search=True,
        max_tool_calls=int(cfg["limits"]["critic_max_tool_calls"]),
        reasoning_effort="low",
    )
    budget.add(res.usage)
    d = res.data
    op.critic_fatal = bool(d.get("fatal", False))
    op.critic_case = str(d.get("critic_case", ""))
    op.contrary_evidence = list(dict.fromkeys(op.contrary_evidence + list(d.get("contrary_evidence", []))))
    op.unknowns = list(dict.fromkeys(op.unknowns + list(d.get("unknowns", []))))
    op.falsification_conditions = list(dict.fromkeys(op.falsification_conditions + list(d.get("falsification_conditions", []))))
    op.evidence_confidence = min(op.evidence_confidence, float(d.get("evidence_confidence", op.evidence_confidence)))
    return op, res.usage


def judge(ai: AIClient, cfg: dict[str, Any], op: Opportunity, budget: Budget) -> tuple[Opportunity, Usage | None]:
    reserve = float(cfg["budget"]["reserve_judge_usd"])
    if not budget.can_spend(reserve):
        return op, None
    vcfg = _vertical_config(op.vertical)
    model = cfg["models"]["judge"]
    prompt = f"""Judge this opportunity against an ABSOLUTE bar, not against other candidates.\nVertical configuration:\n{json.dumps(vcfg, ensure_ascii=False)}\n\nOpportunity + critic:\n{op.model_dump_json(indent=2)}\n\nReturn ONLY JSON: {{\"status\":\"survived\"|\"watch\"|\"rejected\",\"vertical_fatal\":bool,\"decision_reason\":str,\"judgment_confidence\":0..1,\"major_risks\":[str],\"unknowns\":[str]}}. Do not recommend buying, voting trading or executing. 'survived' means merits HQ attention/research, not action."""
    res = ai.json_research(
        model=model,
        instructions="You are Scout Vertical Judgment. Apply the specialist rubric and fatal conditions. Exciting upside cannot compensate for fatal evidence failures.",
        prompt=prompt,
        max_output_tokens=cfg["limits"]["judge_max_output_tokens"],
        web_search=False,
        reasoning_effort="low",
    )
    budget.add(res.usage)
    d = res.data
    op.vertical_fatal = bool(d.get("vertical_fatal", False))
    op.status = d.get("status", "rejected")
    if op.critic_fatal or op.vertical_fatal:
        op.status = "rejected"
    op.decision_reason = str(d.get("decision_reason", ""))
    op.judgment_confidence = float(d.get("judgment_confidence", 0))
    op.major_risks = list(dict.fromkeys(op.major_risks + list(d.get("major_risks", [])))
    op.unknowns = list(dict.fromkeys(op.unknowns + list(d.get("unknowns", [])))
    op.last_updated = utcnow()
    return op, res.usage


def daily_cost_so_far() -> float:
    today = datetime.now(timezone.utc).date().isoformat()
    total = 0.0
    for r in read_jsonl(ROOT / "state" / "runs.jsonl"):
        if str(r.get("started_at", "")).startswith(today):
            total += float(r.get("cost_usd", 0))
    return total


def select_lenses(lenses: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    if not lenses:
        return []
    n = max(1, min(int(cfg["limits"]["lenses_per_cycle"]), len(lenses)))
    prior_cycles = sum(1 for r in read_jsonl(ROOT / "state" / "runs.jsonl") if r.get("mode") == "cycle")
    start = (prior_cycles * n) % len(lenses)
    return [lenses[(start + i) % len(lenses)] for i in range(n)]


def run_cycle() -> RunRecord:
    cfg = load_yaml(ROOT / "config" / "scout.yaml")
    lenses = load_yaml(ROOT / "config" / "lenses.yaml").get("lenses", [])
    ai = AIClient(cfg["pricing"])
    budget = Budget(float(cfg["budget"]["cycle_usd"]), float(cfg["budget"]["daily_usd"]), daily_cost_so_far())
    run_id = "run_" + uuid.uuid4().hex[:12]
    started = utcnow()

    stored_dicts = read_jsonl(ROOT / "state" / "survivors.jsonl") + read_jsonl(ROOT / "state" / "rejected.jsonl") + read_jsonl(ROOT / "state" / "watch.jsonl")
    stored = []
    for x in stored_dicts:
        try: stored.append(Opportunity.model_validate(x))
        except Exception: pass

    selected_lenses = select_lenses(lenses, cfg)
    candidates, usages = discover(ai, cfg, selected_lenses, budget)
    raw_count = len(candidates)
    filtered: list[Opportunity] = []
    rejected: list[Opportunity] = []
    for op in candidates:
        reasons = hard_gate_reasons(op)
        if is_duplicate(op, stored + filtered, float(cfg["limits"]["dedupe_similarity"])):
            reasons.append("duplicate")
        if reasons:
            op.status = "rejected"
            op.decision_reason = "hard_gate:" + ",".join(reasons)
            rejected.append(op)
        else:
            filtered.append(op)

    # Deterministic prioritization for scarce critic slots: evidence confidence first.
    filtered.sort(key=lambda x: x.evidence_confidence, reverse=True)
    critic_pool = filtered[: int(cfg["limits"]["max_candidates_to_critic"])]
    critiqued: list[Opportunity] = []
    critic_reviews = 0
    for op in critic_pool:
        op, u = critic(ai, cfg, op, budget)
        if u: usages.append(u); critic_reviews += 1
        if op.critic_fatal:
            op.status = "rejected"; op.decision_reason = "critic_fatal"; rejected.append(op)
        else:
            critiqued.append(op)

    judge_pool = critiqued[: int(cfg["limits"]["max_candidates_to_judge"])]
    judged: list[Opportunity] = []
    judge_reviews = 0
    for op in judge_pool:
        op, u = judge(ai, cfg, op, budget)
        if u: usages.append(u); judge_reviews += 1
        judged.append(op)

    # Candidates that cleared hard gates but did not receive scarce paid review are WATCH, not silently discarded.
    reviewed_ids = {x.opportunity_id for x in judged} | {x.opportunity_id for x in rejected}
    deferred = [x for x in filtered if x.opportunity_id not in reviewed_ids]
    for op in deferred:
        op.status = "watch"
        op.decision_reason = "deferred_by_cost_or_review_cap"

    final = rejected + judged + deferred
    for op in final:
        target = {"survived":"survivors.jsonl","watch":"watch.jsonl","rejected":"rejected.jsonl"}.get(op.status, "rejected.jsonl")
        append_jsonl(ROOT / "state" / target, op.model_dump())

    rec = RunRecord(
        run_id=run_id, started_at=started, finished_at=utcnow(), mode="cycle",
        discovery_batches=sum(1 for u in usages if u.model == cfg["models"]["discovery"]),
        raw_candidates=raw_count, normalized_candidates=len(candidates), critic_reviews=critic_reviews,
        judge_reviews=judge_reviews, survivors=sum(x.status=="survived" for x in final),
        watches=sum(x.status=="watch" for x in final), rejected=sum(x.status=="rejected" for x in final),
        cost_usd=round(sum(u.estimated_cost_usd for u in usages), 6), budget_exhausted=not budget.can_spend(),
        notes=["lenses=" + ",".join(str(x.get("id", x.get("name", "unknown"))) for x in selected_lenses)],
    )
    append_jsonl(ROOT / "state" / "runs.jsonl", rec.model_dump())
    write_report()
    return rec


def write_report() -> Path:
    runs = read_jsonl(ROOT / "state" / "runs.jsonl")
    survivors = read_jsonl(ROOT / "state" / "survivors.jsonl")
    watches = read_jsonl(ROOT / "state" / "watch.jsonl")
    last = runs[-1] if runs else {}
    lines = ["# SCOUT V0 — Latest Report", "", f"Generated: {utcnow()}", ""]
    if last:
        lines += [
            f"- Discovery batches: {last.get('discovery_batches',0)}",
            f"- Candidates normalized: {last.get('normalized_candidates',0)}",
            f"- Critic reviews: {last.get('critic_reviews',0)}",
            f"- Judge reviews: {last.get('judge_reviews',0)}",
            f"- New survivors: {last.get('survivors',0)}",
            f"- New watches: {last.get('watches',0)}",
            f"- Rejected: {last.get('rejected',0)}",
            f"- Run cost estimate: ${last.get('cost_usd',0):.4f}",
            "",
        ]
    lines.append("## Survivors")
    recent = survivors[-20:]
    if not recent:
        lines.append("No survivors. Scout does not manufacture a daily winner.")
    else:
        for x in recent:
            lines += [f"### {x.get('name','Unnamed')}", f"- Vertical: {x.get('vertical')}", f"- Thesis: {x.get('thesis')}", f"- Why now: {x.get('why_now')}", f"- Decision: {x.get('decision_reason')}", ""]
    lines.append("## Watch / unresolved")
    if not watches:
        lines.append("None.")
    else:
        for x in watches[-10:]:
            lines.append(f"- **{x.get('name')}** — {x.get('decision_reason')}")
    path = ROOT / "reports" / "latest.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
