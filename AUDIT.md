# Scout V0 run #3 audit

Audited main at 705b292f0434499217626996441b2e9eb6f387eb, including all
four application modules, packaging, both workflows, model/budget/lens/vertical
configuration, tests, calibration fixtures, and persisted run/report.

## Demonstrated failure

[Scout V0 run #3](https://github.com/barandiego/Scout/actions/runs/36946861496)
checked out 79eb016c0adc73079ab970aebaa87d1c46c6db38. Installation,
compile, dependency checks, nine tests, validation, calibration, and model-list
preflight succeeded. Discovery then received HTTP 400:

> Web Search cannot be used with JSON mode.

The shared adapter sent web_search plus text.format.type=json_object. Criticism
would send the same incompatible combination. Run state correctly persisted
the failure and reported no returned usage; it never reached criticism/judgment.
Model-list preflight proves availability, not request/tool compatibility.

## Consolidated correction

- Discovery and critic use capped web search with prompted JSON, parsed locally.
  The judge retains JSON mode without tools. No extra extraction/repair call.
- Completed object output and tool-returned sources are required. Prose,
  truncation/refusal, empty output, missing candidate lists, malformed candidates,
  and invalid critic/judge decisions fail closed.
- Strict decision validation requires actual booleans, bounded finite confidence,
  string lists, and valid lifecycle statuses. No missing fatal flag defaults.
- Recheck deterministic fatal gates after criticism lowers evidence confidence.
- Ground URLs only to completed search source metadata; preserve query strings
  so different documents at the same path cannot substitute for a consulted URL.
- Count returned usage before parsing/schema validation. Persist the budget's
  full cost even when a stage fails; include critic/judge diagnostics in reports.
- Disable automatic SDK retries and bound request time, avoiding hidden repeat
  generation attempts. Missing pricing or nonpositive caps fail before sending.

## Regression evidence

Offline HTTP transport tests exercise the actual OpenAI SDK serialization,
AIClient, all three stages, grounding, gates, budgets, JSONL state and report.
They assert search requests contain no JSON-mode format and judgment contains no
search tools. Failure cases assert no repair request, no survivor, preserved cost
and failure state. Existing dedupe, material-update and calibration coverage stays.

## Remaining V0 limits

- No live generation was performed in this audit. Offline SDK tests cannot prove
  model/tool availability, live evidence quality, latency or prompt adherence.
- Dollar budgets use estimates and stage reserves, not provider-side hard spending
  ceilings. A request can exceed its reserve; a transport failure may have incurred
  cost without returning usage. Project-level financial limits remain necessary.
- Existing append-only watch records are deduplicated on subsequent discovery
  unless material new evidence appears. V0 has no independent watch retry queue.
  Reports also show historical records rather than a compacted latest-state view.
- Configuration validation is shallow; existing configured values were inspected.
  Model-list preflight does not validate tool/output combinations.
- Workflow state persistence uses rebase/push and can still conflict with concurrent
  edits; it is serialized against other Scout workflow runs, not human pushes.

Keep this fix off main until Diego separately authorizes live operation: the
existing main workflow schedules paid cycles. CI on fix branches and PRs is unpaid.
