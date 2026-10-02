# Scout V0 AI-boundary reliability audit

Audited main `3399ee2b88941b7389a207ad95e170ff8b6d9c6c` (2026-10-02 UTC),
all application code/config/workflows/tests, six live jobs and current persisted
state. Implementation branch: `redesign/v0-ai-boundary`. No paid calls, preflight,
workflow dispatch, secret inspection, main edits, or merge during this work.

## Failure history: independently inspected Actions logs

| Run | Evidence | Root cause |
|---|---|---|
| [1](https://github.com/barandiego/Scout/actions/runs/36942028157) | Editable install failed | Flat-layout package discovery included state/config/reports |
| [2](https://github.com/barandiego/Scout/actions/runs/36942770730) | Test collection SyntaxError | Generated source was not compiled/tested before deployment |
| [3](https://github.com/barandiego/Scout/actions/runs/36946861496) | 9 tests passed; HTTP 400 | Web search plus JSON mode rejected by API |
| [4](https://github.com/barandiego/Scout/actions/runs/36947127910) | Same HTTP 400 after preflight | Model listing did not test request/tool compatibility |
| [5](https://github.com/barandiego/Scout/actions/runs/36952919077) | 36 tests passed; incomplete response; $0.015705 estimate | Expected response state classified as whole-run failure |
| [6](https://github.com/barandiego/Scout/actions/runs/36953865666) | 36 tests passed; `float("high")`; $0.014751 estimate | Eager untrusted conversion destroyed the batch before normalization returned |

Run #5's historical persisted diagnostics do NOT establish the incomplete reason;
it must not be retrospectively asserted as max_output_tokens. New diagnostics
preserve that field. Four legacy run rows are parseable and IDs unique; no candidate
files exist. Known estimates sum to **$0.030456**. Runs #3/#4 report zero without
returned usage, not independently reconciled billing. Run #6 recorded zero raw and
normalized candidates despite returning discovery content: telemetry depended on
successful batch return. Current report matches that last failed row.

The architectural defect was shared across discovery, review validation, metering,
and persistence: valid-looking model objects were too close to trusted state.
Early packaging/syntax defects are distinct, but collectively the history also
shows why compile/happy-path tests and model-list preflight were insufficient.

## Correction

- Added two focused modules: `boundary.py` (raw parsing/coercion/grounding) and
  `state.py` (atomic run+record transactions). Kept common core, three stages and
  YAML verticals; no new runtime dependency, framework, service or database.
- Discovery emits a small signal rather than a full Opportunity. Canonical records
  whitelist fields, enforce strict types/invariants, and ignore model lifecycle/IDs.
- Each raw item has diagnostics; invalid siblings are isolated. Review parsing is
  tolerant only where conversion is unambiguous. Unknown required review fields
  fail closed. Reviewer flags and post-critic gates guard survival independently.
- Response accounting precedes interpretation; failure responses retain usage.
  Transport failure is infrastructure; incomplete/malformed model output degrades.
  Unknown cost and interrupted requests cannot look like free budget after restart.
- One atomic JSONL authority keeps costs, finalized records and run outcomes together.
  Latest-state reporting avoids displaying an old survivor after a material rejection.
- CI includes the redesign branch, denies test network access, and keeps schedule off.
  Live workflow state-upload/persistence checks prevent simply running again after
  unconfirmed Git persistence. This is a small safety gate, not a monitoring system.

## Official API contract checked 2026-10-02

- [Responses reference](https://developers.openai.com/api/reference/python/resources/responses/methods/create)
  and installed OpenAI Python SDK 3.23.0: built-in max_tool_calls caps the total tool
  calls; max_output_tokens covers reasoning as well as visible output. Unknown fields
  are not control instructions. Noncompleted responses cannot yield canonical records.
- [Web search](https://developers.openai.com/api/docs/guides/tools-web-search): request
  `include=["web_search_call.action.sources"]`. Source lists differ from inline
  citations. Only completed top-level tool sources qualify for URL grounding.
- [Reasoning](https://developers.openai.com/api/docs/guides/reasoning): incomplete
  responses may incur input/reasoning cost without visible answer. Track reason and
  output/reasoning usage; do not bill reasoning twice.
- [Text/prompt guide](https://developers.openai.com/api/docs/guides/prompt-engineering):
  text need not be output item zero; aggregate message output_text parts defensively.
- [Structured output guide](https://developers.openai.com/api/docs/guides/structured-outputs):
  JSON mode does not validate Scout's schema and can still encounter incomplete/refusal
  states. Keep prompted JSON for web tools based on directly observed #3/#4 rejection;
  do not claim all tool/structured-output combinations are universally unsupported.
- [Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna) and
  [Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra): both current
  pages list Responses/web search support. Existing input/cached/output prices match
  the pages; cache writes use 1.25x input and long contexts >272K use tiered factors.
  Account-level availability is not proved by documentation; no metadata call made.
- [Pricing](https://developers.openai.com/api/docs/pricing): search is $10/1,000 calls
  plus model-priced search content. Returned tool-item counting is a best-effort
  estimate, not organization billing reconciliation.

## Offline test evidence

**194 pytest cases**, including **1,000 seeded raw-value iterations** and **100
seeded complete-pipeline iterations** inside two tests; five existing calibration
cases pass. No fuzz dependency or generation calls. Dedicated venv installed fresh:
OpenAI 3.23.0, Pydantic 2.13.5, pytest 9.1.1. All tests run with socket access denied.

| Requested category | Coverage |
|---|---|
| A discovery | empty/missing/null/string container, nonobjects, mixed siblings, 100 candidates, duplicates |
| B/C types | 18 confidence cases, 13 booleans, full-cycle confidence+sibling matrix |
| D missing fields | required identity quarantine; economic gate failures; optional defaults |
| E provenance | actual returned sources only; fabricated/malformed/duplicate/tracking/scheme/query variants; partial evidence discard |
| F/G API | JSON/fences/prose/truncation/ambiguous objects, empty text, tool-only, incomplete reasons, failed, timeout, exception, missing/bad usage, future fields |
| H/I reviews | fatal strings, missing flags, malformed confidence/status, low post-critic confidence, no accidental survivor, review caps count failed attempts |
| J budget | stage reserves, daily block, no critic/judge budget, consumed failed-call cost, uncertain usage/restart |
| K state | malformed historical lines, duplicate/conflicting runs, atomic replace fault, process death, lock exclusion, report failure, strict survivor reload |
| L dedupe | exact/fuzzy, same entity/different thesis, genuine-source update, fake update, reopen rejection, no stale survivor |
| M injection | instructions in candidate/page-derived fields remain data; cannot control lifecycle, budgets or execution |
| N extremes | huge strings, multilingual/emoji/surrogates, nested dictionaries, whitespace, deterministic fuzz |

Eight named full scenarios: (1) fatal/watch/survivor, (2) malformed sibling with two
survivors, (3) incomplete metered discovery, (4) malformed critic with surviving
sibling, (5) malformed judge, (6) zero candidates, (7) budget exhausted after
discovery, (8) Open Finance Chile specialist routing. SDK HTTP tests exercise actual
request serialization and full persistence/reporting with mocked Responses replies.

## Remaining limits and controlled live validation

No finite tests prove immunity to all future provider behavior. Grounding proves URL
membership, not claim truth, recency, independent publisher identity, or factual
source classification. Models may still be misled by web content. Prompt tests prove
deterministic control isolation, not semantic immunity to prompt injection.

Budget estimates are not hard provider spending caps. Token/search usage can be lost
on transport failure. A daily uncertainty block is conservative. Late/midnight
billing and remote runner loss still require artifact/ledger reconciliation. Stage
reserves can be exceeded by one request. No billing/account settings were changed.
Atomic replacement prevents torn local writes; unavailable disks cannot preserve new
data. GitHub artifact/push paths require live workflow confirmation. No independent
watch retry queue, embedding dedupe, or long-term log compaction is introduced.

One separately authorized live cycle is justified after branch CI passes. Schedule
must remain off. No repair/retry calls. Predeclare:

1. **Operational PASS:** run completes safely (zero survivors is valid), returned
   usage/cost is recorded, no unhandled candidate exception, canonical invariants
   hold, and report/artifact/Git state commit agree. Estimated cost <=$0.08 and no
   calls after an unavailable reserve. An incomplete response demonstrates safe
   degradation but is not a completed-discovery validation.
2. **End-to-end coverage PASS:** at least one naturally discovered grounded candidate
   passes gates and reaches critic AND judge, with coherent decisions and state.
   It need not survive. Do not weaken gates or force a candidate to obtain coverage.
3. If discovery finds nothing, operational success stands but live reviewer coverage
   remains unproven. HQ decides next steps; no automatic second paid attempt.
4. Any infra/state/accounting/provenance inconsistency is FAIL. Investigate durable
   diagnostics offline before another independently authorized paid cycle.

Do not enable unattended scheduling merely because the Action is green. HQ must
review these live checks and the remaining economic/evidence-quality uncertainty.
