# SCOUT — Public Procurement Chile

Status: **autonomous read-only monitoring / no OpenAI / no procurement actions**. The vertical is scheduled separately from the paid Scout V0 discovery cycle.

## Hypothesis

Can a small eligible supplier repeatedly identify Chilean Compra Ágil opportunities where it could source the requested goods, submit a market-competitive quotation, fulfill the order, and retain attractive risk-adjusted economics?

The experiment is designed to falsify that hypothesis. Zero survivors is valid.

## Phase boundary

Current implementation supports the deterministic substrate for **Phase 1 historical market reconstruction** and the invariants needed by later counterfactual/shadow evaluation. It does not submit quotations, buy products, contact buyers/suppliers, register entities, invoice, pay, or commit capital.

It remains outside the paid Scout V0 lens rotation. A separate `procurement-chile.yml` workflow performs bounded read-only incremental ChileCompra API monitoring every four hours, persists normalized state plus a sanitized report, and uses no OpenAI.

## Official data contract used

The adapter follows ChileCompra's May 2026 Compra Ágil V2 guide:

- base: `https://api2.mercadopublico.cl`
- list/search: `GET /v2/compra-agil`
- detail: `GET /v2/compra-agil/{codigo}`
- authentication: `ticket` HTTP header
- maximum documented page size: 50
- publication/change windows and pagination are deterministic inputs
- `id_orden_compra` is treated as the reliable OC-emission indicator
- fields the official guide labels unconfirmed/unreliable remain optional; they are never synthesized

A universal numeric daily quota is not assumed. The client has its own hard request cap and fails closed on 429.

## Information leakage rule

Procurement outcomes can be stored after resolution, but a historical decision may use only `TimedEvidence` whose `observed_at <= decision_at <= bid_deadline`. Post-deadline winning prices are accepted only by reconciliation, never by the simulated decision.

Historical sourcing is intentionally strict: a current price cannot silently stand in for a historical price. With the default policy, a WOULD_BID decision requires price-bearing sourcing evidence that is explicitly marked historically exact, plus separate pre-deadline competitive evidence.

## Deterministic economics

The economics engine computes gross spread, financing cost, total cost, expected net contribution, net margin, return on deployed capital and profit per capital-day. Taxes/fees are explicit inputs rather than inferred. Sensitivity helpers can stress acquisition, logistics and revenue assumptions.

## State

`ProcurementStore` is separate from `state/transactions.jsonl`. It uses Scout's atomic write primitive and immutable logical events for:

- historical normalized snapshots;
- shadow decisions;
- observed outcomes;
- monotonic synchronization cursors.

Repeated identical writes are idempotent; conflicting writes to an immutable shadow-decision key fail closed.

## Manual commands

Offline fixture normalization (no network):

```bash
python -m scout.procurement_chile validate-fixture tests/fixtures/compra_agil_detail_documented.json
```

A bounded real historical read and an incremental `monitor` command are enabled for this authorized read-only vertical. Both require `CHILECOMPRA_TICKET` from trusted environment/Actions secrets. No OpenAI call is involved.

## Bounded real API validation — 2026-10-03

A manual, read-only validation against the real Compra Ágil API was completed from this branch with no OpenAI calls and no procurement actions.

Observed sequence:

- historical list access for 2026-04-01 through 2026-04-02 succeeded with a personal ChileCompra ticket;
- the first bounded detail probe exposed that real API timestamps are ISO-parseable but timezone-naive, despite the fixture having timezone-aware examples;
- the real detail payload also exposed `id_orden_compra` at top level rather than only in the documented nested OC shape;
- compatibility was corrected conservatively: real API timestamps are preserved without inventing timezone semantics, and the observed top-level OC ID is accepted as a fallback;
- the final bounded sample used 5 total HTTP requests: 1 list page plus 4 detail attempts;
- all 4 detail responses normalized successfully;
- all 4 records were resolved;
- all 4 were structurally reconstructable under the current deterministic gates;
- all 4 exposed observable supplier quote totals;
- 0/4 exposed a purchase-order indicator in the sampled records.

This is a **PASS for API accessibility, real response shape, and approximately six-month historical availability**. It is not evidence that the business thesis is profitable.

## Remaining limits

1. The sample is intentionally tiny and does not establish population-level coverage or stability across agencies, categories, dates, and states.
2. Procurement-side competition is reconstructable in the sample, but historical acquisition cost remains external to ChileCompra and is still the main economic bottleneck.
3. Real API timestamps do not carry timezone offsets. They are preserved as returned; Scout does not infer UTC or Chile time.
4. OC/selection fields remain incomplete or unreliable enough that outcome scoring must stay conservative.
5. A lower hypothetical price is not automatically a hypothetical win unless price-only selection is independently verified; otherwise reconciliation records only `price_competitive`.

## Autonomous monitor

The scheduled monitor uses incremental ChileCompra change windows with a durable monotonic cursor. It advances the cursor only after a bounded run without API failures or request-budget exhaustion. Pre-cursor runs start with a six-hour lookback. Each run is capped at 25 total HTTP requests, 2 list pages and 20 detail requests.

The report surfaces structurally reconstructable procurements in `publicada` state as research/watch candidates. This is **not** a profitability claim: supplier acquisition cost is still absent, so Scout does not fabricate sourcing economics.

## Next gate

Let the autonomous monitor accumulate coverage evidence while HQ focuses elsewhere. The next economic gate remains external sourcing-cost evidence and a defensible profitability test. No quotation, supplier/buyer contact, purchase, payment, registration or capital commitment is authorized.
