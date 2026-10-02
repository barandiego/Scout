# Scout V0 — authoritative specification

## Mission and scope

Discover economic signals, judge them, store 0..N genuine opportunities, report to
SCOUT — HQ. Never trade, buy, contact third parties, allocate business capital,
deploy businesses, or create Pocket/Forge projects. Verticals remain YAML rubrics
attached to one common core. Open Finance Chile retains CMF/Banco Central/SFA/API
and implementation coverage. Deep due diligence belongs to RADAR.

## Non-negotiable AI boundary

**External probabilistic output is never trusted state.**

`Responses/search → raw signal envelope → tolerant parsing/sanitation → per-candidate validation/grounding → canonical Opportunity → gates/dedupe → independent critic → vertical judge → atomic state → report`

`RawDiscoverySignal` accepts uncertain values. It cannot be persisted as an
Opportunity. Python owns IDs, timestamps, lifecycle, reviewed flags, URL provenance,
budgets and dedupe. Discovery supplies a small signal, economic hypothesis,
participation path and source claims; it does not generate the full database record.
Old field names remain accepted at this boundary. The production path always passes
the actual adapter's returned source set. No caller gets implicit grounding.

`Opportunity` is strict and revalidated before storage. Survivor validation requires
both completed valid reviews, no fatal flag, all evidence/economic gates, and judge
confidence >=0.55. Critic can lower, never raise, evidence confidence. Gates run again
after criticism and before survival. A valid shape does not prove the model's claims
are true: HQ must still investigate a survivor before taking action.

## Deterministic conversion policy

| Input | Policy |
|---|---|
| Probability number or numeric string in [0,1] | Accept; finite only; bool excluded |
| Explicit `"80%"` | 0.8 |
| Bare 80, 8, negative, >1, `high`, `medium`, null, list/object, NaN/Infinity | Unknown; discovery confidence 0; required review confidence invalid |
| bool, case-insensitive true/false, yes/no, string/numeric 1/0 | Convert explicitly |
| Other boolean input | Unknown; discovery gate false; review decision invalid |
| String | Strip, replace invalid Unicode, cap at 2,000 characters; no conversion of objects/numbers to prose |
| String-list field | Scalar string becomes singleton; keep distinct nonblank strings, first 20 entries; drop other values |
| Evidence | List or singleton object; inspect first 20; discard bad items independently |
| URL | HTTP(S), valid host/port, no userinfo, whitespace, control characters or backslashes; max 4,096 chars |
| URL equivalence | Lowercase scheme/host, IDNA, default ports, strip fragment/utm_*/gclid/fbclid; preserve scheme, www, path and substantive query/order |
| Discovery container | Must have candidates list; missing/null/string is degraded discovery, not infrastructure failure |
| Response text | One complete JSON object, optional fences/prose; reject duplicate keys, competing objects, truncated containers, >250 KB |
| Extra fields | Ignore raw fields outside explicit whitelist; forbid extra canonical record fields |
| Missing title/name, signal, thesis | Quarantine candidate; never invent identity |
| Missing economic path/evidence/actionability | Canonical rejected record after gates |

At most 100 raw entries are scanned, stopping at the configured canonical candidate
cap (currently 3). Quarantined entries do not consume valid slots. Diagnostics record
indexes, reasons, coercions and source counts, not full discarded payloads.

## Evidence and fatal gates

Grounding is exact normalized membership in completed top-level
`web_search_call.action.sources`. Message text, nested impostors, annotations alone,
and model-authored URLs cannot add trusted source membership. Evidence stores the
model claim, model source classification, normalized URL/domain and returned URL.
**Grounded means the tool returned the URL, not that its text proves the claim.**
Source classifications are model judgments, not certified publisher classifications.

All fatal requirements are conjunctive: real premise, two distinct grounded source
URLs with claims, at least one credible claimed source class, evidence confidence
>=0.55, value-capture mechanism, actionability, participation path, no unupdated
duplicate, no critic fatal contradiction and no vertical fatal condition. Unknown
never substitutes for success. No single weighted score can override these gates.

Duplicate identity includes thesis, not just entity. Token overlap is deterministic;
no embeddings. Reopening requires a sufficiently long update summary AND new grounded
credible-class evidence; this only permits re-review, not automatic promotion or
proof of materiality. Same-batch duplicates cannot reopen one another. Latest state
by opportunity ID is authoritative; historical lifecycle versions remain auditable.

## Stage/run semantics

Fail **closed economically**, **safe operationally**. Malformed raw candidates are
quarantined; invalid critic/judge output becomes WATCH; fatal gates become REJECTED.
Other candidates continue within attempt and budget caps. No automatic repair call
or paid retry. Model output cannot change instructions or enable execution tools.
Prompt injection resistance is not a guarantee that models cannot be misled.

| Outcome | Meaning | CLI ok |
|---|---|---|
| SUCCESS | Correct operation, including empty discovery / zero survivors / intentional review-cap deferral | true |
| DEGRADED_SUCCESS | Incomplete/malformed model response or candidate/review failures, safely isolated | true |
| BUDGET_STOP | Reserve unavailable or daily cost uncertainty blocks continuation | true |
| FAILED_INFRASTRUCTURE | Credentials/API transport/server, configuration, state corruption, disk or implementation failure | false |
| RUNNING | Durable in-progress checkpoint, never a completed successful run | false |

Infrastructure takes precedence over budget stop, then degradation. An incomplete
response is not salvaged into candidates; all available usage is still charged.
Report includes stage/status/reason, candidate counts, provenance counts, review
attempts/completions, disposition counts, aggregates, usage and remaining budget.

## Costs, state, and recovery

`AIClient` is the sole paid boundary: Responses API, retries=0, timeout=60s, bounded
output/tools. Web research uses prompted JSON without JSON mode; tool-free judgment
uses JSON mode and still validates locally. Empty/no-source discovery is valid;
no-source criticism cannot authorize survival.

Record stage/model/input/cached/cache-write/output/reasoning tokens, web tool items,
estimated cost and cumulative run cost before interpreting output. Reasoning tokens
are already included in output. Count returned web-call items conservatively; this
is not exact billing. Optional absent cache-write count is zero. Invalid usage retains
known counts, flags uncertainty and blocks further spending that UTC day.

Current configured estimates: $0.08/cycle, $0.25/UTC-day, discovery/critic/judge
reserves $0.035/$0.030/$0.020, 3 candidates, 1 critic, 1 judge, 2 web calls per search
stage. A stage can exceed its reserve; these are estimated admission controls, not
provider-enforced billing ceilings. No account/billing setting is changed here.

`state/transactions.jsonl` is the new atomic authority: one row contains a run and
its finalized records. Write-ahead pending-stage reservation, post-response cost
checkpoint and final checkpoint each replace the whole file atomically (temp,
flush/fsync, replace). Process death leaves a reservation; subsequent cycles block
paid work for that UTC day. Linux flock enforces one local writer. Existing
`runs.jsonl` and old disposition files are immutable legacy input, strictly read;
corruption stops spending rather than silently losing costs. Identical legacy run
IDs count once; conflicting duplicates fail closed. Reports are regenerable views.

GitHub Actions also serializes runs, uploads state recovery artifacts before Git
persistence, and requires preceding cycle persistence to have succeeded before a
new paid cycle. Report/calibration runs do not clear that safety check. If persistence
fails, recover the artifact and reconcile costs before separately authorizing more
paid work; no automated recovery invents missing cost. Runner loss before upload and
Git push cannot be made durable by local atomic writes alone.

## Verification and activation

Schedule remains **absent/disabled**. CI has no API secret and tests deny sockets.
Install, compile, pip check, full pytest, config and all five calibrations must pass.
The fake-provider harness and real-SDK/mock-HTTP suite are the regression defense.
See AUDIT.md for evidence, limits and the separately authorized live-validation bar.
