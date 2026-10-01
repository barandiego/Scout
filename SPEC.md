# SCOUT V0 — Authoritative Build Specification

## Mission
Scout V0 is an autonomous, evidence-first economic opportunity intelligence system. It continuously converts observed signals into opportunity hypotheses, challenges them, and persists/report only what survives. Output volume is determined by reality: 0..N survivors.

Core lifecycle:
`DISCOVER -> NORMALIZE -> HARD GATES -> DEDUPE -> ADVERSARIAL CRITIC -> VERTICAL JUDGMENT -> SURVIVE / WATCH / REJECT -> STORE -> REPORT`

## Scope
V0 may search, read, generate hypotheses, criticize, judge, store/update records, deduplicate, track cost, and report. V0 may not trade, buy, spend business capital, contact suppliers, send external communications, create companies/stores, deploy commercial products, or create/modify Pocket/Forge projects.

## Statuses
- `candidate`: normalized but not fully judged.
- `rejected`: failed hard gate, critic, or vertical judgment.
- `watch`: plausible but blocked by missing evidence/timing.
- `survived`: clears the absolute survival bar and merits HQ review.
- `escalate_to_radar`: HQ-only downstream decision; V0 never sets this automatically.

## Hard gates
A candidate cannot survive unless all are true:
1. Real underlying entity/change/market.
2. Credible evidence exists.
3. Plausible economic value-capture mechanism exists.
4. Opportunity remains actionable.
5. Not a material duplicate of a stored opportunity.
6. Diego has a realistic direct or future participation path.
7. Adversarial critic finds no fatal contradiction.
8. Vertical-specific fatal conditions pass.

Hard gates are conjunctive. Upside never compensates for a fatal failure.

## Opportunity Record
Stable fields:
- opportunity_id, discovered_at, last_updated
- name, type, vertical, geography
- signal, what_changed, why_now
- thesis, value_capture_mechanism
- evidence, primary_sources, independent_sources, contrary_evidence, evidence_confidence
- capital_required, diego_hours_initial, diego_hours_ongoing, ai_leverage
- time_horizon
- major_risks, unknowns, falsification_conditions
- critic_case
- status, hq_decision, decision_reason
- future_updates, eventual_outcome, lessons

## Core / vertical split
Core owns lifecycle, schemas, deterministic gates, dedupe, persistence, budgets, routing and reporting. Verticals are configuration: specialist sources, prompts, criteria and fatal conditions. Adding a vertical should not require core-code changes.

## Runtime boundary
`AIClient` is the only domain-facing interface to OpenAI. V0 uses Responses API + built-in web search. Python owns deterministic orchestration. This boundary must permit later replacement/augmentation by a persistent runtime such as Dots without changing state schemas or lifecycle.

## Cost policy
Every response records model, input tokens, cached tokens when available, output tokens, web-search calls, estimated API cost, run cumulative cost and daily cumulative cost. Hard ceilings stop further AI work safely. Breadth is cheap; critic/judgment are capped.

Initial controls are deliberately conservative and configurable:
- 3 discovery lenses per cycle, rotated across the lens set
- max 6 normalized candidates per cycle
- max 1 critic entrant per cycle
- max 1 judge entrant per cycle
- web-search tool calls capped per model response
- initial internal ceiling: US$0.06 per cycle and US$0.25 per UTC day
- OpenAI project monthly limit remains an independent second safety layer

## Scheduling
GitHub Actions:
- discovery cycle every 4 hours
- morning report at 08:00 America/Santiago (11:00 UTC while UTC-3)
- manual workflow dispatch
State and reports are committed back to the repository by the workflow.

## Calibration acceptance
Before ACTIVE, verify judgment on:
- Auzmendi: plausible geographic-arbitrage opportunity; validation required; not auto-active.
- Aclara Resources: route public markets; financing/dilution/technical execution are central; never auto-buy.
- Open Finance Chile: structural/regulatory opportunity; route specialist vertical; business model uncertain.
- Generic AI-wrapper SaaS: reject absent unusual evidence of demand/defensibility.
- Deliberately fake/weak hypothesis: fail evidence/reality gates.

ACTIVE requires: automatic wake-up, research, structured candidates, gates, critic, vertical judgment, persistence, dedupe, budget compliance, variable 0..N survivors, and report generation.
