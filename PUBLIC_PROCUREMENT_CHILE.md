# SCOUT — Public Procurement Chile

Status: **experimental / historical validation only**. This subsystem is deliberately isolated from the active Scout V0 discovery schedule.

## Hypothesis

Can a small eligible supplier repeatedly identify Chilean Compra Ágil opportunities where it could source the requested goods, submit a market-competitive quotation, fulfill the order, and retain attractive risk-adjusted economics?

The experiment is designed to falsify that hypothesis. Zero survivors is valid.

## Phase boundary

Current implementation supports the deterministic substrate for **Phase 1 historical market reconstruction** and the invariants needed by later counterfactual/shadow evaluation. It does not submit quotations, buy products, contact buyers/suppliers, register entities, invoice, pay, or commit capital.

It is **not** registered in `config/verticals/`, is not added to `config/lenses.yaml`, and is not invoked by `.github/workflows/scout.yml`. This prevents the active paid Scout V0 cycle from spending on or executing this experiment.

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

A bounded real historical read exists but is disabled in config by default. Enabling it is a separate explicit governance decision and requires `CHILECOMPRA_TICKET` in the environment. No OpenAI call is involved.

## Known limits before a real historical run

1. ChileCompra documents date-range queries but does not document a guaranteed retention horizon for all historical Compra Ágil records.
2. Procurement-side competition may be reconstructable, but historical acquisition cost is external to ChileCompra and is the main economic bottleneck.
3. Some selection/OC fields are documented as unreliable or not confirmed in actual responses, so outcome scoring must remain conservative.
4. A lower hypothetical price is not automatically a hypothetical win unless price-only selection is independently verified; otherwise reconciliation records only `price_competitive`.

## Next gate

Before switching `live_api_enabled` to true, review this PR, obtain/use a ChileCompra ticket only via environment secret, choose a small historical date window, and approve a bounded request budget. The first real run should validate the already-tested contract, not debug it.
