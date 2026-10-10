"""Cost-free Scout library derived only from canonical state. No execution authority."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .models import Opportunity
from .state import Store, atomic_write


def _one_line(value: str, limit: int = 420) -> str:
    """Escape model-authored strings in the human-readable Markdown view."""
    return " ".join(str(value).split())[:limit].rstrip().replace("<", "‹").replace(">", "›").replace("|", "¦")


def _sort_key(op: Opportunity):
    """Research review queue, NOT projected revenue or probability of success."""
    return (0 if op.status == "survived" else 1,
            -int(op.critic_reviewed and op.judge_reviewed),
            -sum(bool(e.grounded) for e in op.evidence),
            -int(op.actionable), op.name.casefold(), op.opportunity_id)


def _card(op: Opportunity) -> dict:
    evidence = [{"title": e.title, "url": e.url, "source_type": e.source_type,
                 "grounded_in_provider_search": e.grounded, "claim": e.claim}
                for e in op.evidence]
    gaps = list(dict.fromkeys(
        [x for x in op.unknowns if x.strip()] +
        [x for x in op.falsification_conditions if x.strip()]))[:5]
    if not gaps:
        gaps = ["Identify a real buyer, purchasing trigger, distribution route and net unit economics."]
    missing = []
    if not op.critic_reviewed or not op.judge_reviewed:
        missing.append("independent_critic_and_judge")
    if sum(bool(e.grounded) for e in op.evidence) < 2:
        missing.append("two_grounded_sources")
    if not op.actionable:
        missing.append("actionable_participation_path")
    if not op.value_capture_mechanism or op.value_capture_mechanism.lower() == "unknown":
        missing.append("value_capture_mechanism")
    missing.append("external_buyer_and_unit_economics_validation")
    return {
        "id": op.opportunity_id, "title": op.name,
        "vertical": op.vertical, "type": op.type, "geography": op.geography,
        "discovery_lens": op.discovery_lens,
        "status": op.status,
        "research_status": ("HQ_RESEARCH_NOT_EXECUTION_AUTHORITY" if op.status == "survived"
                            else "WATCH_REQUIRES_VALIDATION"),
        "authorized_for_execution": False,
        "verified_sales": None,
        "discovered_at": op.discovered_at,
        "last_record_updated_at": op.last_updated,
        "thesis": op.thesis, "why_now": op.why_now,
        "value_capture_mechanism": op.value_capture_mechanism,
        "participation_path": op.participation_path,
        "estimated_capital": op.capital_required,
        "estimated_founder_hours_initial": op.diego_hours_initial,
        "estimated_founder_hours_ongoing": op.diego_hours_ongoing,
        "ai_leverage": op.ai_leverage,
        "judgment": op.decision_reason,
        "critic_reviewed": op.critic_reviewed,
        "judge_reviewed": op.judge_reviewed,
        "evidence_confidence_model_estimate": op.evidence_confidence,
        "evidence": evidence, "unknowns": list(op.unknowns),
        "contrary_evidence": list(op.contrary_evidence),
        "falsification_conditions": list(op.falsification_conditions),
        "next_validation_questions": gaps,
        "missing_execution_proof": missing,
        "material_update": op.material_update,
        "warning": "Model-authored thesis; grounded URLs do not prove buyers, access, affordability, sales or profit.",
    }


def build_snapshot(opportunities: list[Opportunity], *, generated_at: str) -> dict:
    when = datetime.fromisoformat(generated_at)
    if when.tzinfo is None:
        raise ValueError("LIBRARY_REQUIRES_TIMEZONE")
    latest = {}
    for op in opportunities:
        if not isinstance(op, Opportunity):
            raise TypeError("CANONICAL_OPPORTUNITIES_REQUIRED")
        latest[op.opportunity_id] = op
    unique = list(latest.values())
    cards = [_card(op) for op in sorted(
        (op for op in unique if op.status in ("watch", "survived")), key=_sort_key)]
    counts = Counter(op.status for op in unique)
    return {
        "schema_version": 1, "generated_at": when.astimezone(timezone.utc).isoformat(),
        "source": "SCOUT_CANONICAL_PERSISTED_STATE",
        "total_distinct_opportunities": len(unique),
        "watch": counts["watch"], "survived": counts["survived"],
        "rejected_excluded": counts["rejected"],
        "reviewed_cards": sum(c["critic_reviewed"] and c["judge_reviewed"] for c in cards),
        "execution_authorized": 0, "external_customer_validation_proven": False,
        "external_revenue_verified": False, "cards": cards,
        "interpretation": "Research backlog only; a survived Scout candidate is HQ-worthy research, not a validated business.",
    }


def render_markdown(snapshot: dict) -> str:
    lines = [
        "# Scout — opportunity library", "",
        "Generated: " + snapshot["generated_at"], "",
        "**Research inventory, not verified ready-to-launch businesses.**", "",
        f"- Active research: {len(snapshot['cards'])} ({snapshot['survived']} HQ survivors, {snapshot['watch']} watches)",
        f"- Rejected opportunities excluded: {snapshot['rejected_excluded']}",
        f"- Critic-and-judge reviewed: {snapshot['reviewed_cards']}",
        "- Autonomous execution authorization: 0", "",
        "## How to use", "",
        "Choose a candidate, independently verify current sources and a paying buyer, "
        "test distribution and net pricing, and obtain explicit approval for bounded "
        "execution. The original evidence gates stay in force.", "",
    ]
    for c in snapshot["cards"]:
        lines.extend([
            "### " + _one_line(c["title"]) + " [" + _one_line(c["id"], 140) + "]",
            "- Status: " + c["research_status"] + " | " + _one_line(c["vertical"]) + " | " + _one_line(c["geography"]),
            "- Thesis: " + _one_line(c["thesis"], 530),
            "- Value capture: " + _one_line(c["value_capture_mechanism"], 440),
            "- Participation hypothesis: " + _one_line(c["participation_path"], 550),
            "- Critic/judge: " + _one_line(c["judgment"], 440),
            "- Next evidence gaps: " + "; ".join(_one_line(x, 165) for x in c["next_validation_questions"][:3]),
            "- Missing execution proof: " + ", ".join(c["missing_execution_proof"]),
            "- Grounded and model-supplied sources: " + "; ".join(_one_line(e["url"], 180) for e in c["evidence"][:4]),
            "",
        ])
    if not snapshot["cards"]:
        lines.append("No active research cards. The system does not invent an idea.")
    return "\n".join(lines).rstrip("\n") + "\n"


def write_library(root: Path) -> dict:
    """Read state, write two derived reports. Zero network/model/paid calls."""
    data = build_snapshot(Store(root).opportunities(),
                          generated_at=datetime.now(timezone.utc).isoformat())
    path = root / "reports"
    atomic_write(path / "library.json",
                 json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n")
    atomic_write(path / "library.md", render_markdown(data))
    # No new candidate, paid inference or external action. A downstream
    # first-dollar shortlist only asks what still requires real buyer proof.
    from .commercial import write_commercial_queue
    commercial = write_commercial_queue(root, data)
    return {"cards": len(data["cards"]), "survived": data["survived"],
            "watch": data["watch"], "rejected_excluded": data["rejected_excluded"],
            "execution_authorized": 0, "commercial": commercial,
            "outputs": ["reports/library.json", "reports/library.md",
                        "reports/commercial_queue.json", "reports/commercial_queue.md"]}
