from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator, field_validator

Status = Literal['candidate','rejected','watch','survived']

class CriticDecision(BaseModel):
    model_config=ConfigDict(strict=True)
    fatal: bool
    critic_case: str=Field(min_length=1)
    contrary_evidence: list[str]
    unknowns: list[str]
    falsification_conditions: list[str]
    evidence_confidence: float=Field(ge=0,le=1,allow_inf_nan=False)

class JudgeDecision(BaseModel):
    model_config=ConfigDict(strict=True)
    status: Literal['survived','watch','rejected']
    vertical_fatal: bool
    decision_reason: str=Field(min_length=1)
    judgment_confidence: float=Field(ge=0,le=1,allow_inf_nan=False)
    major_risks: list[str]
    unknowns: list[str]

class EvidenceItem(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", validate_assignment=True, str_max_length=4096)
    grounded: bool = False
    returned_url: str = ""
    domain: str = ""
    title: str
    url: str
    source_type: Literal['primary','independent','other'] = 'other'
    claim: str

class Opportunity(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", validate_assignment=True, str_max_length=2000, str_strip_whitespace=True, allow_inf_nan=False)
    opportunity_id: str
    discovered_at: str
    last_updated: str
    name: str = Field(min_length=1)
    type: str
    vertical: str = 'general'
    geography: str = 'global'
    discovery_lens: str = ''
    signal: str = Field(min_length=1)
    what_changed: str
    why_now: str
    thesis: str = Field(min_length=1)
    value_capture_mechanism: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    primary_sources: list[str] = Field(default_factory=list)
    independent_sources: list[str] = Field(default_factory=list)
    contrary_evidence: list[str] = Field(default_factory=list)
    evidence_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    capital_required: str = 'unknown'
    diego_hours_initial: str = 'unknown'
    diego_hours_ongoing: str = 'unknown'
    ai_leverage: str = 'unknown'
    time_horizon: str = 'unknown'
    major_risks: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    falsification_conditions: list[str] = Field(default_factory=list)
    critic_case: str = ''
    status: Status = 'candidate'
    hq_decision: str = ''
    decision_reason: str = ''
    future_updates: list[str] = Field(default_factory=list)
    eventual_outcome: str = ''
    lessons: list[str] = Field(default_factory=list)
    real: bool = False
    actionable: bool = False
    participation_path: str = ''
    material_update: bool = False
    update_summary: str = ''
    critic_reviewed: bool = False
    judge_reviewed: bool = False
    critic_fatal: bool = False
    vertical_fatal: bool = False
    judgment_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode='after')
    def validate_evidence(self):
        from .boundary import url_key
        for e in self.evidence:
            if not url_key(e.url):
                raise ValueError('invalid_evidence_url')
            if e.grounded and (not e.returned_url or url_key(e.returned_url) != e.url):
                raise ValueError('invalid_grounding_metadata')
        if self.primary_sources != [e.url for e in self.evidence if e.source_type == 'primary']:
            raise ValueError('inconsistent_primary_sources')
        if self.independent_sources != [e.url for e in self.evidence if e.source_type == 'independent']:
            raise ValueError('inconsistent_independent_sources')
        if self.status == 'survived':
            from .pipeline import hard_gate_reasons
            if (not self.critic_reviewed or not self.judge_reviewed or self.critic_fatal
                    or self.vertical_fatal or self.judgment_confidence < .55 or hard_gate_reasons(self)):
                raise ValueError('invalid_survivor')
        return self

    @field_validator('discovered_at', 'last_updated')
    @classmethod
    def aware_timestamp(cls, value):
        from datetime import datetime
        if datetime.fromisoformat(value).tzinfo is None:
            raise ValueError('timestamp_requires_timezone')
        return value

class Usage(BaseModel):
    model_config = ConfigDict(strict=True, allow_inf_nan=False)
    stage: str = ''
    available: bool = True
    reasoning_tokens: int = Field(default=0, ge=0)
    cache_write_tokens: int = Field(default=0, ge=0)
    accounting_notes: list[str] = Field(default_factory=list)
    cumulative_cost_usd: float = 0.0
    model: str
    input_tokens: int = Field(default=0, ge=0)
    cached_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    web_search_calls: int = Field(default=0, ge=0)
    estimated_cost_usd: float = Field(default=0.0, ge=0)

class RunRecord(BaseModel):
    model_config = ConfigDict(strict=True, allow_inf_nan=False)
    outcome: Literal['RUNNING', 'SUCCESS', 'DEGRADED_SUCCESS', 'FAILED_INFRASTRUCTURE', 'BUDGET_STOP'] = 'RUNNING'
    pending_stage: str = ''
    reserved_usd: float = Field(default=0.0, ge=0)
    cost_uncertain: bool = False
    usages: list[Usage] = Field(default_factory=list)
    diagnostics: list[dict] = Field(default_factory=list)
    lenses: list[str] = Field(default_factory=list)
    normalization_rejected: int = 0
    parseable_candidates: int = 0
    grounded_sources: int = 0
    rejection_reasons: dict[str, int] = Field(default_factory=dict)
    errors_by_stage: dict[str, int] = Field(default_factory=dict)
    budget_remaining_usd: float = 0.0
    stop_reason: str = ''
    run_id: str
    started_at: str
    finished_at: str
    mode: str
    ok: bool = True
    discovery_batches: int = 0
    raw_candidates: int = 0
    normalized_candidates: int = 0
    duplicates_skipped: int = 0
    critic_attempts: int = 0
    judge_attempts: int = 0
    critic_reviews: int = 0
    judge_reviews: int = 0
    survivors: int = 0
    watches: int = 0
    rejected: int = 0
    errors: int = 0
    cost_usd: float = Field(default=0.0, ge=0)
    budget_exhausted: bool = False
    notes: list[str] = Field(default_factory=list)


    @field_validator('started_at', 'finished_at')
    @classmethod
    def aware_timestamp(cls, value, info):
        from datetime import datetime
        if not value and info.field_name == 'finished_at':
            return value
        if datetime.fromisoformat(value).tzinfo is None:
            raise ValueError('timestamp_requires_timezone')
        return value
