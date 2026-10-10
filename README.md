# Scout V0

Evidence-first economic opportunity intelligence for SCOUT — HQ.

`DISCOVER → normalize/ground → gates/dedupe → CRITIC → vertical JUDGE → STORE → REPORT`

External probabilistic output is never trusted state. A malformed candidate is
quarantined; invalid reviewer output fails closed; siblings continue. Zero survivors
is a valid result. Scout never performs economic execution.

## Runtime and state

Six small application modules, including the CLI entry point: Python, Responses API,
Pydantic, YAML, atomic JSONL. No agents framework or new services. Linux GitHub
Actions is the supported cycle runtime (local state writer uses flock).

`state/transactions.jsonl` holds atomic run/cost/finalized-record checkpoints. The
old `runs.jsonl` and disposition files remain immutable legacy input. Reports display
latest opportunity states. Do not hand-edit cost checkpoints to bypass a stop.

## Offline verification

```bash
pip install -e '.[dev]'
python -m compileall -q scout tests
python -m pip check
pytest -q
python -m scout.cli validate
python -m scout.cli calibrate
python -m scout.cli report
python -m scout.cli library
```

CI has no API key; tests deny sockets and use fake providers/mock HTTP. The live
`cycle` command is paid and requires separate authorization. `preflight` lists model
metadata; it does not prove generation/tool compatibility.

## Status

**ACTIVE V0 — activated 2 October 2026.** GitHub Actions runs one Scout cycle every
4 hours (`0 */4 * * *`, UTC) and manual dispatch remains available. Defaults remain
3 signals, 1 critic, 1 judge, $0.08/cycle and $0.50/UTC-day estimated guards.
Unknown/interrupted cost blocks further paid work for the UTC day. If a GitHub state
push fails, recover its uploaded state artifact and reconcile before another cycle;
the workflow blocks unconfirmed previous cycle persistence.

See [SPEC.md](SPEC.md) for conversion/invariant policies and [AUDIT.md](AUDIT.md) for
six-run findings, 194-test evidence, current API sources and the live PASS definition.

## Opportunity library

After each GitHub Actions discovery cycle, Scout derives
[reports/library.md](reports/library.md) and [reports/library.json](reports/library.json)
from authoritative persisted opportunities. This is pure Python, with zero new
model calls, zero additional API spend, no trading and no auto-business execution.
Watches and HQ survivors remain research candidates until a real buyer, viable
net unit economics and execution permissions have been checked independently.
Rejected candidates remain in durable state but are excluded from the pick-list.
All existing critic, judge, budget, dedupe and commercial gates are unchanged.


## V1 — high-volume opportunity research

The original Scout V0 governed provider pipeline continues with its existing
budget and safety gates. A **separate public-source radar** now pulls launches,
research and industry signals across AI, robotics, NFC, local commerce,
agriculture, energy and Chilean technology adoption. It costs no model tokens.

- [V1 operating design and limitations](docs/SCOUT_V1_WIDE_RADAR.md)
- [Current public radar](reports/radar.md) and [machine-readable leads](reports/radar.json)
- [Innovation/competition briefing queue](reports/innovation_backlog.md)
- [Existing canonical opportunity library](reports/library.md)

Offline/test commands:

```bash
python -m scout.cli radar
python -m scout.cli library
pytest -q
```

The public radar's raw signals are NOT evidence of paying customers,
seller scarcity, investment value or verified executable opportunities.
A research-qualified idea beyond the old one-per-cycle review cap now
remains WATCH/deferred_by_review_cap for subsequent reviews.
No paid research trial, key change or increase to the live budget is
triggered by this release.
