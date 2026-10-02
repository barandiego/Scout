# SCOUT V0 — Authoritative Build Specification

## Mission
Autonomous evidence-first opportunity intelligence. Output is determined by reality: 0..N survivors.

`DISCOVER -> NORMALIZE/GROUND -> HARD GATES -> DEDUPE -> ADVERSARIAL CRITIC -> VERTICAL JUDGMENT -> SURVIVE/WATCH/REJECT -> STORE -> REPORT`

## Boundaries
V0 may search, read, hypothesize, criticize, judge, store/update records, deduplicate, meter cost and report. It may not trade, buy, spend business capital, contact suppliers/third parties, create companies/stores, deploy commercial products, or create/modify Pocket/Forge projects.

## Hard gates
A survivor requires: real underlying entity/change; at least two distinct web-grounded sources; credible evidence class; plausible value capture; current actionability; non-duplication or material new evidence; realistic Diego participation path; no fatal critic contradiction; and no vertical fatal condition. Upside never compensates for a fatal failure.

## Common record
Stable fields cover identity/time, type/vertical/geography/lens, signal/change/why-now, thesis/value capture, evidence and contrary evidence, confidence, capital/Diego-hours/AI leverage, horizon, risks/unknowns/falsification, critic case, lifecycle/HQ decision, updates/outcome/lessons.

## Core / vertical split
Core owns lifecycle, schemas, grounding, deterministic gates, dedupe, persistence, budgets, routing and reporting. Verticals are configuration: specialist source preferences, criteria and fatal conditions. Current specialist configs: general, public markets, geographic arbitrage, Open Finance Chile.

## Runtime boundary
`AIClient` is the sole OpenAI boundary. V0 uses Responses API + built-in web search. Python owns deterministic control. This keeps V0 replaceable by a future persistent runtime without changing state/lifecycle.

## Cost and safety
Every model response records tokens, search calls and best-effort estimated cost. Search calls/output are capped. Initial guardrails: 3 lenses/cycle; <=6 normalized candidates; <=1 critic; <=1 judge; $0.08/cycle and $0.25/UTC-day. The OpenAI project monthly limit is a second, account-level backstop.

## Scheduling
GitHub Actions runs discovery around every 4 hours, creates a morning report around 08:00 Chile under the current UTC-3 offset, and supports manual dispatch. Reports do not force a survivor.

## Reliability
A separate CI workflow runs on code pushes/PRs without API secrets. It must pass install, compile, dependency check, unit/integration tests, config validation and calibration. Live cycles additionally run an API/model preflight before paid research and persist state/report even when a later stage fails.

## Calibration
Known examples: Auzmendi -> geographic-arbitrage validation; Aclara -> public-markets research, never auto-buy; Open Finance Chile -> specialist vertical; generic AI wrapper -> reject absent unusual evidence; fabricated hypothesis -> fail evidence gate. ACTIVE still requires a successful real cycle proving research, grounding, critic, judgment, persistence, dedupe, budget behavior and reporting.
