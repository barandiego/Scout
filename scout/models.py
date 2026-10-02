from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field

Status = Literal["candidate", "rejected", "watch", "survived"]

class EvidenceItem(BaseModel):
    title: str
    url: str
    source_type: Literal["primary", "independent", "other"] = "other"
    claim: str

class Opportunity(BaseModel):
    opportunity_id: str
    discovered_at: str
    last_updated: str
    name: str
    type: str
    vertical: str = "general"
    geography: str = "global"
    discovery_lens: str = ""
    signal: str
    what_changed: str
    why_now: str
    thesis: str
    value_capture_mechanism: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    primary_sources: list[str] = Field(default_factory=list)
    independent_sources: list[str] = Field(default_factory=list)
    contrary_evidence: list[str] = Field(default_factory=list)
    evidence_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    capital_required: str = "unknown"
    diego_hours_initial: str = "unknown"
    diego_hours_ongoing: str = "unknown"
    ai_leverage: str = "unknown"
    time_horizon: str = "unknown"
    major_risks: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    falsification_conditions: list[str] = Field(default_factory=list)
    critic_case: str = ""
    status: Status = "candidate"
    hq_decision: str = ""
    decision_reason: str = ""
    future_updates: list[str] = Field(default_factory=list)
    eventual_outcome: str = ""
    lessons: list[str] = Field(default_factory=list)
    real: bool = False
    actionable: bool = False
    participation_path: str = ""
    material_update: bool = False
    update_summary: str = ""
    critic_fatal: bool = False
    vertical_fatal: bool = False
    judgment_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

class Usage(BaseModel):
    model: str
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    web_search_calls: int = 0
    estimated_cost_usd: float = 0.0

class RunRecord(BaseModel):
    run_id: str
    started_at: str
    finished_at: str
    mode: str
    ok: bool = True
    discovery_batches: int = 0
    raw_candidates: int = 0
    normalized_candidates: int = 0
    duplicates_skipped: int = 0
    critic_reviews: int = 0
    judge_reviews: int = 0
    survivors: int = 0
    watches: int = 0
    rejected: int = 0
    errors: int = 0
    cost_usd: float = 0.0
    budget_exhausted: bool = False
    notes: list[str] = Field(default_factory=list)
