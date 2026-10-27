from datetime import datetime, timezone
from email.message import Message
from urllib.error import HTTPError

import pytest

from scout import procurement_io
from scout.procurement_core import ProcurementAPIError


@pytest.mark.parametrize("window", ["historical", "changed"])
def test_rate_limit_stops_the_remaining_details(window):
    calls = []
    listing = {"success": "OK", "payload": {"items": [{"codigo": "A"}, {"codigo": "B"}],
                           "paginacion": {"total_paginas": 1, "numero_pagina": 1}}}

    def transport(url, headers, timeout):
        calls.append(url)
        if url.endswith("/v2/compra-agil/A"):
            raise ProcurementAPIError("api_rate_limited")
        if url.endswith("/v2/compra-agil/B"):
            pytest.fail("must not request another detail after rate limit")
        return listing

    client = procurement_io.ChileCompraClient("not-a-secret", request_limit=10,
                                              transport=transport, sleep_fn=lambda _: None)
    common = dict(observed_at="2026-06-04T12:00:00Z", max_pages=1, max_details=2)
    if window == "changed":
        _, diag = client.changed_window(changed_from="2026-06-01T00:00:00Z",
                                        changed_to="2026-06-02T00:00:00Z", **common)
    else:
        _, diag = client.historical_window(published_from="2026-06-01T00:00:00Z",
                                           published_to="2026-06-02T00:00:00Z", **common)
    assert diag["api_failures"] == {"api_rate_limited": 1}
    assert diag["detail_attempts"] == 1
    assert diag["requests_used"] == 2


def test_rate_limit_with_short_retry_after_honors_delay_and_budget():
    calls, sleeps = [], []

    def transport(url, headers, timeout):
        calls.append(url)
        if len(calls) == 1:
            raise procurement_io.RateLimitedError(retry_after_seconds=3)
        return {"payload": {"items": []}}

    client = procurement_io.ChileCompraClient("test", request_limit=2,
                                              transport=transport, sleep_fn=sleeps.append)
    client.list_page()
    assert sleeps == [3]
    assert len(calls) == client.budget.used == 2
    assert client.transient_retries == 1


@pytest.mark.parametrize("delay", [None, 31, -1, float("nan")])
def test_rate_limit_invalid_or_excessive_wait_fails_without_retry(delay):
    calls, sleeps = [], []
    def transport(url, headers, timeout):
        calls.append(url)
        raise procurement_io.RateLimitedError(retry_after_seconds=delay)
    client = procurement_io.ChileCompraClient("test", request_limit=5,
                                              transport=transport, sleep_fn=sleeps.append)
    with pytest.raises(ProcurementAPIError, match="api_rate_limited"):
        client.list_page()
    assert len(calls) == client.budget.used == 1
    assert sleeps == []


def test_transport_captures_retry_after_without_disclosing_url(monkeypatch):
    headers = Message()
    headers["Retry-After"] = "5"
    def reject(request, timeout):
        raise HTTPError(request.full_url, 429, "throttled", headers, None)
    monkeypatch.setattr(procurement_io, "urlopen", reject)
    with pytest.raises(ProcurementAPIError) as caught:
        procurement_io._transport("https://example.invalid/private", {"ticket": "secret"}, 1)
    assert str(caught.value) == "api_rate_limited"
    assert caught.value.retry_after_seconds == 5


def test_retry_after_http_date_uses_utc_and_rejects_invalid():
    now = datetime(2026, 6, 4, 12, 0, 0, tzinfo=timezone.utc)
    assert procurement_io._retry_after_seconds("Thu, 04 Jun 2026 12:00:07 GMT", now) == 7
    assert procurement_io._retry_after_seconds("invalid", now) is None


def test_rate_limit_retry_cannot_exceed_request_budget():
    calls, sleeps = [], []
    def transport(url, headers, timeout):
        calls.append(url)
        raise procurement_io.RateLimitedError(retry_after_seconds=1)
    client = procurement_io.ChileCompraClient("test", request_limit=1,
                                              transport=transport, sleep_fn=sleeps.append)
    with pytest.raises(ProcurementAPIError, match="api_rate_limited"):
        client.list_page()
    assert len(calls) == client.budget.used == 1
    assert sleeps == []


def test_exhausted_rate_limit_keeps_monitor_degraded():
    from scout.procurement_chile import monitor_health
    diag = {"api_failures": {"api_rate_limited": 1}, "budget_exhausted": False}
    assert monitor_health(diag) == (False, "DEGRADED_API_ERRORS")


def test_backfill_does_not_report_rate_limited_partial_work_as_success(tmp_path, monkeypatch, capsys):
    import json
    import sys
    from scout import procurement_chile as cli

    class FixtureClient:
        def __init__(self, *args, **kwargs):
            pass
        def historical_window(self, **kwargs):
            return [], {"api_failures": {"api_rate_limited": 1},
                        "budget_exhausted": False, "malformed_details": 0}

    monkeypatch.setattr(cli, "ChileCompraClient", FixtureClient)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "_config", lambda: {"live_api_enabled": True,
        "limits": {"max_requests_per_run": 25, "max_list_pages": 2, "max_detail_requests": 20}})
    monkeypatch.setenv("CHILECOMPRA_TICKET", "fixture-only")
    monkeypatch.setattr(sys, "argv", ["procurement", "backfill", "--from",
        "2026-06-01T00:00:00Z", "--to", "2026-06-02T00:00:00Z"])
    assert cli._main() == 2
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False
    assert report["diagnostics"]["api_failures"] == {"api_rate_limited": 1}
