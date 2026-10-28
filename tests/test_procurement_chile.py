import copy
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from scout import procurement_chile as procurement_cli
from pydantic import ValidationError

from scout.procurement_chile import (
    ChileCompraClient,
    CounterfactualCandidate,
    DecisionPolicy,
    EconomicsInputs,
    ObservedOutcome,
    ProcurementAPIError,
    ProcurementDataError,
    ProcurementStore,
    RequestBudget,
    TimedEvidence,
    compute_economics,
    historical_decision,
    normalize_detail,
    phase1_report,
    phase1_survivors,
    reconcile,
    reconstructability_reasons,
    stress_economics,
)

FIXTURE = Path(__file__).parent / "fixtures" / "compra_agil_detail_documented.json"
OBSERVED = "2026-06-04T12:00:00+00:00"


def raw_detail():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def record():
    return normalize_detail(raw_detail(), observed_at=OBSERVED)


def economics(**updates):
    base = dict(
        bid_revenue_clp=800000.0,
        acquisition_cost_clp=500000.0,
        logistics_clp=30000.0,
        taxes_and_fees_clp=20000.0,
        other_required_costs_clp=10000.0,
        expected_failure_cost_clp=10000.0,
        capital_required_clp=560000.0,
        capital_days=30,
        annual_financing_rate=0.18,
    )
    base.update(updates)
    return EconomicsInputs(**base)


def policy(**updates):
    base = dict(
        min_net_margin=0.10,
        min_return_on_capital=0.10,
        max_capital_clp=1000000.0,
        max_capital_days=60,
        min_equivalence_confidence=0.85,
        min_evidence_confidence=0.70,
        require_historical_sourcing_price=True,
    )
    base.update(updates)
    return DecisionPolicy(**base)


def evidence(kind, eid, *, observed="2026-06-02T09:00:00+00:00", price=500000.0, exact=True):
    return TimedEvidence(
        evidence_id=eid,
        kind=kind,
        source_url=f"https://evidence.example/{eid}",
        observed_at=observed,
        claim="Sanitized fixture evidence",
        price_clp=price,
        historical_price_exact=exact,
    )


def candidate(**updates):
    base = dict(
        procurement_code="999999-1-COT26",
        decision_at="2026-06-02T12:00:00+00:00",
        bid_deadline="2026-06-02T15:00:00+00:00",
        hypothetical_bid_clp=800000.0,
        maximum_acceptable_bid_clp=820000.0,
        economics=economics(),
        product_equivalence_confidence=0.95,
        evidence_confidence=0.90,
        competitive_price_estimate_clp=850000.0,
        competitive_estimate_evidence_id="comp",
        delivery_feasible=True,
        stock_confirmed=True,
        eligible_supplier=True,
        regulatory_clear=True,
        evidence=[evidence("sourcing", "source"), evidence("competition", "comp", price=850000.0)],
        major_risks=["fixture risk"],
    )
    base.update(updates)
    return CounterfactualCandidate(**base)


def test_official_schema_normalization_and_unreliable_oc_code_preserved_as_unknown():
    r = record()
    assert r.code == "999999-1-COT26"
    assert r.region_code == 13 and r.delivery_days == 5
    assert r.products[0].quantity == 100
    assert len(r.quotes) == 2 and r.quotes[0].total_clp == 853000
    assert r.purchase_order.internal_id == 123456
    assert r.purchase_order.external_code == ""
    assert reconstructability_reasons(r) == []


@pytest.mark.parametrize("mutation,error", [
    (lambda x: x["payload"].pop("codigo"), "missing_code"),
    (lambda x: x["payload"]["fechas"].pop("fecha_cierre"), "missing_required_timestamps"),
    (lambda x: x.update(success="NOK", payload=None), "api_response_not_success"),
])
def test_malformed_required_fields_fail_closed(mutation, error):
    raw = raw_detail(); mutation(raw)
    with pytest.raises(ProcurementDataError, match=error):
        normalize_detail(raw, observed_at=OBSERVED)


def test_missing_optional_fields_are_explicit_and_reconstructability_rejects():
    raw = raw_detail()
    raw["payload"]["entrega"] = {}
    raw["payload"]["productos_solicitados"][0]["unidad_medida"] = None
    raw["payload"]["proveedores_cotizando"] = []
    r = normalize_detail(raw, observed_at=OBSERVED)
    reasons = reconstructability_reasons(r)
    assert {"missing_unit", "missing_delivery_location", "missing_delivery_deadline", "no_observable_competitive_prices"} <= set(reasons)


def test_zero_survivor_is_valid():
    raw = raw_detail(); raw["payload"]["productos_solicitados"] = []
    r = normalize_detail(raw, observed_at=OBSERVED)
    assert phase1_survivors([r]) == []
    report = phase1_report([r])
    assert report["structurally_reconstructable"] == 0


def test_economics_and_working_capital_math():
    result = compute_economics(economics())
    financing = 560000 * 0.18 * 30 / 365
    expected_cost = 500000 + 30000 + 20000 + 10000 + 10000 + financing
    assert result.financing_cost_clp == pytest.approx(financing)
    assert result.total_cost_clp == pytest.approx(expected_cost)
    assert result.expected_net_profit_clp == pytest.approx(800000 - expected_cost)
    assert result.net_margin == pytest.approx(result.expected_net_profit_clp / 800000)
    assert result.return_on_deployed_capital == pytest.approx(result.expected_net_profit_clp / 560000)
    assert result.profit_per_capital_day == pytest.approx(result.expected_net_profit_clp / (560000 * 30))


def test_sensitivity_worsens_profit_without_mutating_input():
    base = economics()
    stressed = stress_economics(base, sourcing_error=.10, logistics_error=.20, revenue_error=-.05)
    assert stressed.expected_net_profit_clp < compute_economics(base).expected_net_profit_clp
    assert base.acquisition_cost_clp == 500000


def test_negative_margin_and_ambiguous_product_are_rejected():
    bad_econ = economics(acquisition_cost_clp=900000.0)
    c = candidate(economics=bad_econ, hypothetical_bid_clp=800000.0)
    d = historical_decision(c, policy())
    assert d.decision == "IGNORE" and "non_positive_expected_profit" in d.reasons
    d = historical_decision(candidate(product_equivalence_confidence=.4), policy())
    assert d.decision == "IGNORE" and "ambiguous_product_equivalence" in d.reasons


def test_working_capital_gate_rejects():
    c = candidate(economics=economics(capital_required_clp=2000000.0))
    d = historical_decision(c, policy())
    assert d.decision == "IGNORE" and "working_capital_too_high" in d.reasons


def test_insufficient_evidence_never_would_bid():
    c = candidate(evidence=[], competitive_price_estimate_clp=None, competitive_estimate_evidence_id="")
    d = historical_decision(c, policy())
    assert d.decision == "INVESTIGATE"
    assert "missing_sourcing_price_evidence" in d.reasons
    assert "missing_predeadline_competitive_evidence" in d.reasons


def test_current_price_cannot_masquerade_as_historical_sourcing():
    c = candidate(evidence=[evidence("sourcing", "source", exact=False), evidence("competition", "comp", price=850000)])
    d = historical_decision(c, policy())
    assert d.decision == "INVESTIGATE" and "historical_sourcing_price_unverified" in d.reasons


def test_noncompetitive_bid_rejected_even_if_under_buyer_budget():
    c = candidate(competitive_price_estimate_clp=750000.0)
    d = historical_decision(c, policy())
    assert d.decision == "IGNORE" and "bid_not_competitive_to_estimate" in d.reasons


def test_historical_information_leakage_is_error_not_low_confidence():
    future = evidence("sourcing", "future", observed="2026-06-03T09:00:00+00:00")
    c = candidate(evidence=[future, evidence("competition", "comp", price=850000)])
    with pytest.raises(ProcurementDataError, match="historical_information_leakage"):
        historical_decision(c, policy())
    with pytest.raises(ProcurementDataError, match="decision_after_deadline"):
        historical_decision(candidate(decision_at="2026-06-02T16:00:00+00:00"), policy())


def test_good_counterfactual_can_reach_would_bid_only_with_predeadline_evidence():
    d = historical_decision(candidate(), policy())
    assert d.decision == "WOULD_BID"
    assert d.expected_profit_clp > 0 and d.evidence_ids == ["source", "comp"]


def test_bid_and_economics_revenue_cannot_diverge():
    with pytest.raises(ValidationError):
        candidate(hypothetical_bid_clp=790000.0)


def test_shadow_decision_immutable_and_restart_idempotent(tmp_path):
    path = tmp_path / "events.jsonl"
    d = historical_decision(candidate(), policy())
    store = ProcurementStore(path)
    assert store.add_shadow_decision(d)
    assert not ProcurementStore(path).add_shadow_decision(d)
    changed = d.model_copy(update={"hypothetical_bid_clp": 799999.0})
    with pytest.raises(ProcurementDataError, match="immutable_event_conflict"):
        ProcurementStore(path).add_shadow_decision(changed)


def test_history_snapshot_idempotent_and_changed_snapshot_is_preserved(tmp_path):
    path = tmp_path / "events.jsonl"
    r = record(); store = ProcurementStore(path)
    assert store.add_history(r)
    assert not ProcurementStore(path).add_history(r)
    changed = r.model_copy(update={"status": "cerrada"})
    assert ProcurementStore(path).add_history(changed)
    events = json.loads("[" + path.read_text().strip().replace("\n", ",") + "]")
    assert len(events) == 2


def test_outcome_reconciliation_does_not_overclaim_win():
    d = historical_decision(candidate(), policy())
    out = ObservedOutcome(procurement_code=d.procurement_code, resolved_at="2026-06-04T00:00:00+00:00",
                          winning_total_clp=850000.0, winning_supplier_rut="11.111.111-1",
                          purchase_order_id=123, price_only_selection_verified=False)
    r = reconcile(d, out)
    assert r.price_competitive is True and r.would_have_won is None
    verified = out.model_copy(update={"price_only_selection_verified": True})
    assert reconcile(d, verified).would_have_won is True


def test_request_budget_fails_before_extra_request():
    b = RequestBudget(2)
    b.spend(); b.spend()
    with pytest.raises(ProcurementAPIError, match="request_budget_exhausted"):
        b.spend()
    assert b.used == 2


def test_client_ticket_is_header_only_and_filters_are_bounded():
    calls = []
    def transport(url, headers, timeout):
        calls.append((url, headers, timeout))
        return {"success": "OK", "payload": {"items": [], "paginacion": {"total_paginas": 1, "numero_pagina": 1}}}
    client = ChileCompraClient("SECRET-TICKET", request_limit=2, transport=transport)
    client.list_page(published_from="2026-06-01T00:00:00Z", published_to="2026-06-02T00:00:00Z", page_size=50, region=13)
    url, headers, timeout = calls[0]
    assert "SECRET-TICKET" not in url and headers == {"ticket": "SECRET-TICKET"}
    params = parse_qs(urlparse(url).query)
    assert params["publicado_desde"] == ["2026-06-01T00:00:00Z"] and params["region"] == ["13"]
    with pytest.raises(ProcurementAPIError, match="invalid_pagination"):
        client.list_page(page_size=51)
    with pytest.raises(ProcurementAPIError, match="mixed_publication_and_change_windows"):
        client.list_page(published_from="a", published_to="b", changed_from="c", changed_to="d")


def test_pagination_duplicate_handling_and_caps():
    detail = raw_detail()
    second = copy.deepcopy(detail); second["payload"]["codigo"] = "999999-2-COT26"
    responses = {
        1: {"success":"OK","payload":{"items":[{"codigo":"999999-1-COT26"},{"codigo":"999999-1-COT26"}],"paginacion":{"total_paginas":2,"numero_pagina":1}}},
        2: {"success":"OK","payload":{"items":[{"codigo":"999999-2-COT26"}],"paginacion":{"total_paginas":2,"numero_pagina":2}}},
    }
    def transport(url, headers, timeout):
        parsed = urlparse(url)
        if parsed.path.endswith("999999-1-COT26"): return detail
        if parsed.path.endswith("999999-2-COT26"): return second
        page = int(parse_qs(parsed.query)["numero_pagina"][0])
        return responses[page]
    client = ChileCompraClient("ticket", request_limit=10, transport=transport)
    records, diag = client.historical_window(
        published_from="2026-06-01T00:00:00Z", published_to="2026-06-05T00:00:00Z",
        observed_at=OBSERVED, max_pages=2, max_details=2)
    assert [r.code for r in records] == ["999999-1-COT26", "999999-2-COT26"]
    assert diag == {"pages_fetched": 2, "detail_attempts": 2, "details_fetched": 2, "duplicate_listings": 1, "malformed_details": 0, "malformed_reasons": {}, "malformed_samples": [], "api_failures": {}, "transient_retries": 0, "budget_exhausted": False, "requests_used": 4}


def test_malformed_detail_attempts_are_bounded_and_reported():
    listing = {"success":"OK","payload":{"items":[{"codigo":"A"},{"codigo":"B"},{"codigo":"C"}],"paginacion":{"total_paginas":1,"numero_pagina":1}}}
    malformed = {"success":"NOK","payload":None,"errors":[{"codigo":"fixture","mensaje":"malformed"}]}
    def transport(url, headers, timeout):
        return malformed if "/v2/compra-agil/" in url else listing
    client = ChileCompraClient("ticket", request_limit=3, transport=transport)
    records, diag = client.historical_window(
        published_from="2026-06-01T00:00:00Z", published_to="2026-06-02T00:00:00Z",
        observed_at=OBSERVED, max_pages=1, max_details=2)
    assert records == []
    assert diag["detail_attempts"] == 2
    assert diag["malformed_details"] == 2
    assert diag["malformed_reasons"] == {"api_response_not_success": 2}
    assert len(diag["malformed_samples"]) == 1
    assert diag["malformed_samples"][0]["reason"] == "api_response_not_success"
    assert diag["malformed_samples"][0]["payload_keys"] == []
    assert diag["malformed_samples"][0]["fechas_keys"] == []
    assert diag["requests_used"] == 3


def test_incremental_window_and_cursor_monotonicity(tmp_path):
    seen = []
    def transport(url, headers, timeout):
        seen.append(url)
        return {"success":"OK","payload":{"items":[],"paginacion":{"total_paginas":1,"numero_pagina":1}}}
    client = ChileCompraClient("ticket", request_limit=1, transport=transport)
    client.list_page(changed_from="2026-06-01T00:00:00Z", changed_to="2026-06-02T00:00:00Z")
    params = parse_qs(urlparse(seen[0]).query)
    assert params["ordenar_por"] == ["FechaUltimaModificacion"]
    path = tmp_path / "events.jsonl"; store = ProcurementStore(path)
    assert store.set_cursor("2026-06-02T00:00:00Z")
    assert ProcurementStore(path).latest_cursor() == "2026-06-02T00:00:00+00:00"
    assert not ProcurementStore(path).set_cursor("2026-06-02T00:00:00Z")
    with pytest.raises(ProcurementDataError, match="sync_cursor_regression"):
        ProcurementStore(path).set_cursor("2026-06-01T00:00:00Z")


def test_changed_window_uses_incremental_change_filters():
    seen = []
    def transport(url, headers, timeout):
        seen.append(url)
        return {"success":"OK","payload":{"items":[],"paginacion":{"total_paginas":1,"numero_pagina":1}}}
    client = ChileCompraClient("ticket", request_limit=2, transport=transport)
    records, diag = client.changed_window(
        changed_from="2026-06-01T00:00:00Z",
        changed_to="2026-06-01T04:00:00Z",
        observed_at=OBSERVED,
        max_pages=1,
        max_details=1,
        states=["publicada","cerrada"],
    )
    assert records == []
    params = parse_qs(urlparse(seen[0]).query)
    assert params["cambio_desde"] == ["2026-06-01T00:00:00Z"]
    assert params["cambio_hasta"] == ["2026-06-01T04:00:00Z"]
    assert params["ordenar_por"] == ["FechaUltimaModificacion"]
    assert params["estado"] == ["publicada,cerrada"]
    assert diag["requests_used"] == 1


def test_malformed_timestamp_shape_is_sanitized():
    raw = raw_detail()
    raw["payload"]["fechas"]["fecha_cierre"] = "not-a-timestamp"
    calls = 0
    listing = {"success":"OK","payload":{"items":[{"codigo":"999999-1-COT26"}],"paginacion":{"total_paginas":1,"numero_pagina":1}}}
    def transport(url, headers, timeout):
        nonlocal calls
        calls += 1
        return raw if "/v2/compra-agil/" in url else listing
    client = ChileCompraClient("ticket", request_limit=2, transport=transport)
    records, diag = client.historical_window(
        published_from="2026-06-01T00:00:00Z", published_to="2026-06-02T00:00:00Z",
        observed_at=OBSERVED, max_pages=1, max_details=1)
    assert records == []
    sample = diag["malformed_samples"][0]
    assert sample["code"] == "999999-1-COT26"
    assert sample["reason"] == "missing_required_timestamps"
    assert sample["date_shape"]["fecha_cierre"] == {
        "present": True, "type": "str", "parseable_iso": False, "timezone_aware": False
    }
    assert "Fixture de �tiles estandarizados" not in json.dumps(sample, ensure_ascii=False)


def test_real_api_naive_timestamps_are_preserved_without_invented_timezone():
    raw = raw_detail()
    raw["payload"]["fechas"]["fecha_publicacion"] = "2026-06-01T12:00:00"
    raw["payload"]["fechas"]["fecha_cierre"] = "2026-06-02T15:00:00"
    raw["payload"]["fechas"]["fecha_ultimo_cambio"] = "2026-06-03T12:00:00"
    raw["payload"]["convocatoria"]["fecha_cierre_primer_llamado"] = "2026-06-02T15:00:00"
    r = normalize_detail(raw, observed_at=OBSERVED)
    assert r.published_at == "2026-06-01T12:00:00"
    assert r.closes_at == "2026-06-02T15:00:00"
    assert r.last_changed_at == "2026-06-03T12:00:00"
    assert r.first_call_closes_at == "2026-06-02T15:00:00"


def test_observed_top_level_purchase_order_id_is_supported():
    raw = raw_detail()
    raw["payload"]["orden_compra"] = {}
    raw["payload"]["id_orden_compra"] = 654321
    r = normalize_detail(raw, observed_at=OBSERVED)
    assert r.purchase_order.internal_id == 654321


def test_documented_nested_purchase_order_id_takes_precedence():
    raw = raw_detail()
    raw["payload"]["id_orden_compra"] = 654321
    r = normalize_detail(raw, observed_at=OBSERVED)
    assert r.purchase_order.internal_id == 123456


def test_transient_504_retries_and_recovers_within_request_budget():
    detail = raw_detail()
    listing = {"success":"OK","payload":{"items":[{"codigo":"999999-1-COT26"}],"paginacion":{"total_paginas":1,"numero_pagina":1}}}
    calls = []
    sleeps = []
    def transport(url, headers, timeout):
        calls.append(url)
        if "/v2/compra-agil/" not in url:
            return listing
        detail_calls = sum("/v2/compra-agil/" in x for x in calls)
        if detail_calls == 1:
            raise ProcurementAPIError("api_http_504")
        return detail
    client = ChileCompraClient("ticket", request_limit=4, transport=transport, retry_limit=2, retry_backoff_seconds=1, sleep_fn=sleeps.append)
    records, diag = client.historical_window(
        published_from="2026-06-01T00:00:00Z", published_to="2026-06-02T00:00:00Z",
        observed_at=OBSERVED, max_pages=1, max_details=1)
    assert len(records) == 1
    assert diag["transient_retries"] == 1
    assert diag["api_failures"] == {}
    assert diag["requests_used"] == 3
    assert sleeps == [1.0]


def test_transient_504_never_exceeds_global_request_budget():
    listing = {"success":"OK","payload":{"items":[{"codigo":"A"},{"codigo":"B"}],"paginacion":{"total_paginas":1,"numero_pagina":1}}}
    def transport(url, headers, timeout):
        if "/v2/compra-agil/" not in url:
            return listing
        raise ProcurementAPIError("api_http_504")
    client = ChileCompraClient("ticket", request_limit=3, transport=transport, retry_limit=2, retry_backoff_seconds=0, sleep_fn=lambda _: None)
    records, diag = client.historical_window(
        published_from="2026-06-01T00:00:00Z", published_to="2026-06-02T00:00:00Z",
        observed_at=OBSERVED, max_pages=1, max_details=2)
    assert records == []
    assert diag["requests_used"] == 3
    assert diag["transient_retries"] == 1
    assert diag["api_failures"] == {"api_http_504": 1}
    assert diag["budget_exhausted"] is True


def test_rate_limit_is_not_retried():
    calls = 0
    def transport(url, headers, timeout):
        nonlocal calls
        calls += 1
        raise ProcurementAPIError("api_rate_limited")
    client = ChileCompraClient("ticket", request_limit=5, transport=transport, retry_limit=2, retry_backoff_seconds=0, sleep_fn=lambda _: None)
    with pytest.raises(ProcurementAPIError, match="api_rate_limited"):
        client.list_page(published_from="2026-06-01T00:00:00Z", published_to="2026-06-02T00:00:00Z")
    assert calls == 1
    assert client.budget.used == 1
    assert client.transient_retries == 0


def test_monitor_transient_error_classification_is_fail_closed():
    assert "api_http_504" in procurement_cli.TRANSIENT_MONITOR_ERRORS
    assert "api_transport_error" in procurement_cli.TRANSIENT_MONITOR_ERRORS
    assert "api_rate_limited" in procurement_cli.TRANSIENT_MONITOR_ERRORS
    assert "api_http_400" not in procurement_cli.TRANSIENT_MONITOR_ERRORS
    assert "api_http_401" not in procurement_cli.TRANSIENT_MONITOR_ERRORS


def test_monitor_health_is_complete_only_with_full_authoritative_window():
    assert procurement_cli.monitor_health({
        "api_failures": {}, "budget_exhausted": False,
    }) == (True, "COMPLETE")
    assert procurement_cli.monitor_health({
        "api_failures": {"api_http_504": 2}, "budget_exhausted": False,
    }) == (False, "DEGRADED_API_ERRORS")
    assert procurement_cli.monitor_health({
        "api_failures": {}, "budget_exhausted": True,
    }) == (False, "DEGRADED_INCOMPLETE_REQUEST_BUDGET")
    assert procurement_cli.monitor_health({
        "api_failures": {"api_http_504": 1}, "budget_exhausted": True,
    }) == (False, "DEGRADED_API_ERRORS")


def test_procurement_workflow_persists_degraded_report_before_red_job():
    from pathlib import Path
    workflow = (Path(__file__).resolve().parents[1] /
                ".github/workflows/procurement-chile.yml").read_text(encoding="utf-8")
    assert "if: always() && steps.monitor.outcome != 'skipped'" in workflow
    assert "reports/public_procurement_chile/latest.json" in workflow
    from inspect import getsource
    source = getsource(procurement_cli._main)
    assert "return 0 if healthy else 2" in source


def test_monitor_partial_detail_cap_never_claims_complete():
    # Exactly 20 recovered out of 21, still below the global HTTP budget:
    # the legacy implementation incorrectly marked COMPLETE and advanced.
    listing = {
        "success": "OK",
        "payload": {
            "items": [{"codigo": f"CODE-{i}"} for i in range(21)],
            "paginacion": {"total_paginas": 1, "numero_pagina": 1},
        },
    }

    def transport(url, headers, timeout):
        return raw_detail() if "/v2/compra-agil/" in url else listing

    client = ChileCompraClient("synthetic", request_limit=25, transport=transport)
    rows, diag = client.changed_window(
        changed_from="2026-06-01T00:00:00Z",
        changed_to="2026-06-02T00:00:00Z",
        observed_at=OBSERVED, max_pages=2, max_details=20,
    )
    assert len(rows) == 20
    assert diag["detail_cap_exhausted"] is True
    assert diag["budget_exhausted"] is False
    assert diag["requests_used"] == 21
    assert procurement_cli.monitor_health(diag) == (
        False, "DEGRADED_INCOMPLETE_SOURCE_WINDOW"
    )


def test_exact_detail_limit_on_final_page_is_still_complete():
    listing = {
        "success": "OK",
        "payload": {
            "items": [{"codigo": f"CODE-{i}"} for i in range(20)],
            "paginacion": {"total_paginas": 1, "numero_pagina": 1},
        },
    }
    client = ChileCompraClient(
        "synthetic", request_limit=25,
        transport=lambda url, _headers, _timeout:
            raw_detail() if "/v2/compra-agil/" in url else listing,
    )
    rows, diag = client.changed_window(
        changed_from="2026-06-01T00:00:00Z",
        changed_to="2026-06-02T00:00:00Z",
        observed_at=OBSERVED, max_pages=2, max_details=20,
    )
    assert len(rows) == 20
    assert diag["detail_cap_exhausted"] is False
    assert diag["pagination_incomplete"] is False
    assert procurement_cli.monitor_health(diag) == (True, "COMPLETE")


@pytest.mark.parametrize(("listing", "reason"), [
    (
        {"items": [], "paginacion": {"total_paginas": 2, "numero_pagina": 1}},
        "pagination_incomplete",
    ),
    ({"items": [], "paginacion": {}}, "pagination_invalid"),
    (
        {"items": [], "paginacion": {"total_paginas": 1, "numero_pagina": 2}},
        "pagination_invalid",
    ),
    (
        {"items": {}, "paginacion": {"total_paginas": 1, "numero_pagina": 1}},
        "invalid_listing_items",
    ),
    (
        {"items": [{"missing_code": 1}], "paginacion": {
            "total_paginas": 1, "numero_pagina": 1,
        }},
        "invalid_listing_items",
    ),
])
def test_monitor_invalid_or_capped_listing_fails_closed(listing, reason):
    client = ChileCompraClient(
        "synthetic", request_limit=5,
        transport=lambda *_: {"success": "OK", "payload": listing},
    )
    records, diag = client.changed_window(
        changed_from="2026-06-01T00:00:00Z",
        changed_to="2026-06-02T00:00:00Z",
        observed_at=OBSERVED, max_pages=1, max_details=4,
    )
    assert records == []
    assert diag[reason]
    assert procurement_cli.monitor_health(diag) == (
        False, "DEGRADED_INCOMPLETE_SOURCE_WINDOW"
    )


def test_monitor_malformed_detail_is_not_complete_or_cursor_safe():
    listing = {
        "success": "OK",
        "payload": {
            "items": [{"codigo": "999999-1-COT26"}],
            "paginacion": {"total_paginas": 1, "numero_pagina": 1},
        },
    }
    malformed = raw_detail()
    malformed["payload"]["fechas"].pop("fecha_cierre")

    client = ChileCompraClient(
        "synthetic", request_limit=5,
        transport=lambda url, _headers, _timeout:
            malformed if "/v2/compra-agil/" in url else listing,
    )
    rows, diag = client.changed_window(
        changed_from="2026-06-01T00:00:00Z",
        changed_to="2026-06-02T00:00:00Z",
        observed_at=OBSERVED, max_pages=2, max_details=4,
    )
    assert rows == []
    assert diag["malformed_details"] == 1
    assert procurement_cli.monitor_health(diag) == (
        False, "DEGRADED_MALFORMED_DETAIL"
    )


@pytest.mark.parametrize(("flag", "outcome"), [
    ("detail_cap_exhausted", "DEGRADED_INCOMPLETE_SOURCE_WINDOW"),
    ("pagination_incomplete", "DEGRADED_INCOMPLETE_SOURCE_WINDOW"),
    ("pagination_invalid", "DEGRADED_INCOMPLETE_SOURCE_WINDOW"),
    ("invalid_listing_items", "DEGRADED_INCOMPLETE_SOURCE_WINDOW"),
    ("malformed_details", "DEGRADED_MALFORMED_DETAIL"),
    ("api_failures", "DEGRADED_API_ERRORS"),
])
def test_degraded_monitor_persists_partial_records_and_never_advances_cursor(
    tmp_path, monkeypatch, flag, outcome,
):
    import sys

    previous_cursor = "2026-06-01T00:00:00Z"
    relative_state = "state/public_procurement_chile/events.jsonl"
    relative_report = "reports/public_procurement_chile/latest.json"
    store = ProcurementStore(tmp_path / relative_state)
    assert store.set_cursor(previous_cursor)
    before_cursor = store.latest_cursor()
    partial = record()
    diagnostics = {
        "api_failures": {}, "budget_exhausted": False,
        "malformed_details": 0, "detail_cap_exhausted": False,
        "pagination_incomplete": False, "pagination_invalid": False,
        "invalid_listing_items": 0, "requests_used": 2,
    }
    diagnostics[flag] = {"api_rate_limited": 1} if flag == "api_failures" else 1 if flag in ("invalid_listing_items", "malformed_details") else True

    class FixtureClient:
        def __init__(self, *args, **kwargs):
            pass

        def changed_window(self, **kwargs):
            return [partial], diagnostics

    monkeypatch.setattr(procurement_cli, "ChileCompraClient", FixtureClient)
    monkeypatch.setattr(procurement_cli, "ROOT", tmp_path)
    monkeypatch.setattr(procurement_cli, "_config", lambda: {
        "live_api_enabled": True,
        "limits": {
            "max_requests_per_run": 25, "max_list_pages": 2,
            "max_detail_requests": 20,
        },
        "monitor": {"max_report_candidates": 20},
    })
    monkeypatch.setenv("CHILECOMPRA_TICKET", "fixture-only")
    monkeypatch.setattr(sys, "argv", [
        "procurement", "monitor", "--state", relative_state,
        "--report", relative_report,
    ])
    assert procurement_cli._main() == 2
    recovered = ProcurementStore(tmp_path / relative_state)
    assert recovered.latest_cursor() == before_cursor
    assert sum(e["kind"] == "history_snapshot" for e in recovered.events) == 1
    report = json.loads((tmp_path / relative_report).read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["outcome"] == outcome
    assert report["inserted_history"] == 1
    assert report["diagnostics"][flag]


def test_history_reobservation_with_new_observed_at_is_idempotent(tmp_path):
    path = tmp_path / "events.jsonl"
    original = record()
    later = original.model_copy(update={"source_observed_at": "2026-06-02T00:00:00Z"})
    assert ProcurementStore(path).add_history(original)
    assert not ProcurementStore(path).add_history(later)
    events = ProcurementStore(path).events
    assert len(events) == 1
    assert events[0]["record"]["source_observed_at"] == original.source_observed_at


def test_history_collision_still_raises_immutable_conflict(tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    original = record()
    monkeypatch.setattr(type(original), "digest", lambda self: "0" * 64)
    assert ProcurementStore(path).add_history(original)
    changed = original.model_copy(update={"status": "cerrada", "source_observed_at": "2026-06-02T00:00:00Z"})
    with pytest.raises(ProcurementDataError, match="immutable_event_conflict"):
        ProcurementStore(path).add_history(changed)


def test_history_extra_event_metadata_is_not_silently_ignored(tmp_path):
    path = tmp_path / "events.jsonl"
    original = record()
    assert ProcurementStore(path).add_history(original)
    event = json.loads(path.read_text(encoding="utf-8"))
    event["unexpected_metadata"] = "preserve-conflict"
    path.write_text(json.dumps(event) + "\n", encoding="utf-8")
    later = original.model_copy(update={"source_observed_at": "2026-06-02T00:00:00Z"})
    with pytest.raises(ProcurementDataError, match="immutable_event_conflict"):
        ProcurementStore(path).add_history(later)
