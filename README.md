# Scout V0

Autonomous, evidence-first economic opportunity intelligence for SCOUT — HQ.

Scout wakes in GitHub Actions, rotates through discovery lenses, researches with the OpenAI Responses API + web search, grounds candidate evidence to sources returned by search, applies hard gates and deduplication, sends only a small number into an independent critic and vertical judgment, persists 0..N survivors/watch/rejections, and writes a report.

Scout never performs economic execution.

## Runtime
- GitHub Actions: cloud clock; laptop not required.
- Python: deterministic orchestration, validation, dedupe, budget/state/reporting.
- OpenAI Responses API: research/reasoning; no Agents API.
- JSONL in `state/`: persistent history.
- YAML: lenses, verticals, models and budgets.

## Reliability gates
Every code push runs CI: install -> compile -> dependency check -> tests -> config validation -> calibration. A live cycle additionally performs a no-generation model/API preflight before paid research.

## Commands
```bash
pip install -e '.[dev]'
pytest -q
python -m scout.cli validate
python -m scout.cli calibrate
python -m scout.cli preflight   # needs OPENAI_API_KEY; no generation
python -m scout.cli cycle       # paid live research
python -m scout.cli report
```

## Initial cost posture
3 rotating lenses/cycle, max 6 normalized candidates, max 1 critic + 1 judge, capped web-search calls, $0.08 cycle guardrail and $0.25 UTC-day guardrail. The OpenAI project monthly limit is the independent financial backstop.

GitHub is the technical source of truth. SCOUT — HQ is strategy/review; SCOUT — RADAR is selective deep due diligence.
