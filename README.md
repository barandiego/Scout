# Scout V0

Autonomous, evidence-first economic opportunity intelligence for SCOUT — HQ.

## What it does

Scout wakes on a schedule, rotates through independent discovery lenses, creates evidence-led hypotheses, applies deterministic gates and deduplication, sends only a very small number into adversarial criticism and vertical judgment, persists results, and writes a variable 0..N survivor report.

Scout does **not** execute economic actions.

## Minimal architecture

- Python: orchestration, gates, dedupe, budgets, state, reporting
- OpenAI Responses API + built-in web search: research/reasoning
- YAML: discovery lenses + vertical specialist rubrics
- JSONL: persistent append-only-ish state
- GitHub Actions: 4-hour clock + morning report + manual trigger

## Setup

1. Create a private GitHub repository named `barandiego/Scout`.
2. Push this repository contents.
3. Add repository secret `OPENAI_API_KEY`.
4. Review `config/scout.yaml` budget/model settings.
5. Run `python -m pytest`.
6. Manually dispatch `Scout V0` once with mode `cycle`.
7. Inspect `reports/latest.md`, `state/runs.jsonl`, and cost fields before allowing the schedule to continue.

## Local commands

```bash
python -m pip install -e .
pytest -q
python -m scout.cli cycle
python -m scout.cli report
python -m scout.cli calibrate
```

## Source of truth

The GitHub repository is authoritative for runtime state. SCOUT — HQ is the strategic/review interface; SCOUT — RADAR is selective deep research after HQ escalation.

See `SPEC.md` for the frozen V0 contract.

## Initial cost posture

V0 starts intentionally constrained: at most three lenses per cycle, one critic entrant, one judge entrant, capped web-search calls, US$0.06 estimated per-cycle ceiling and US$0.25 estimated daily ceiling. These are calibration settings, not permanent limits.
