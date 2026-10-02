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
```

CI has no API key; tests deny sockets and use fake providers/mock HTTP. The live
`cycle` command is paid and requires separate authorization. `preflight` lists model
metadata; it does not prove generation/tool compatibility.

## Status

**Automatic schedule disabled.** This restructure does not activate Scout or merge
itself. Defaults remain 3 signals, 1 critic, 1 judge, $0.08/cycle and $0.25/UTC-day
estimated guards. Unknown/interrupted cost blocks further paid work for the UTC day.
If a GitHub state push fails, recover its uploaded state artifact and reconcile before
another cycle; the workflow blocks unconfirmed previous cycle persistence.

See [SPEC.md](SPEC.md) for conversion/invariant policies and [AUDIT.md](AUDIT.md) for
six-run findings, 194-test evidence, current API sources and the live PASS definition.
