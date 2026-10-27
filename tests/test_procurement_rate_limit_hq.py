from email.message import Message
from urllib.error import HTTPError

import pytest

from scout import procurement_io
from scout.procurement_core import ProcurementAPIError


@pytest.mark.parametrize("window", ["historical", "changed"])
@pytest.mark.parametrize("budget", [2, 10])
def test_rate_limit_stops_the_remaining_details(window, budget):
    calls = []
    listing = {"success": "OK", "payload": {
        "items": [{"codigo": "A"}, {"codigo": "B"}],
        "paginacion": {"total_paginas": 1, "numero_pagina": 1},
    }}

    def transport(url, headers, timeout):
        calls.append(url)
        if url.endswith("/v2/compra-agil/A"):
            raise ProcurementAPIError("api_rate_limited")
        if url.endswith("/v2/compra-agil/B"):
            pytest.fail("must not request another detail after rate limit")
        return listing

    client = procurement_io.ChileCompraClient("not-a-secret", request_limit=budget,
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
    assert diag["budget_exhausted"] is (budget == 2)


@pytest.mark.parametrize("retry_after", ["0", "5", "86400", None])
def test_429_never_retries_even_if_retry_after_is_short(monkeypatch, retry_after):
    # ChileCompra documents 429 as a daily quota exhaustion; do not hammer it.
    calls, sleeps = [], []
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after

    def reject(request, timeout):
        calls.append(request.full_url)
        raise HTTPError(request.full_url, 429, "throttled", headers, None)

    monkeypatch.setattr(procurement_io, "urlopen", reject)
    client = procurement_io.ChileCompraClient("fixture-secret", request_limit=5,
                                              sleep_fn=sleeps.append)
    with pytest.raises(ProcurementAPIError) as caught:
        client.list_page()
    assert str(caught.value) == "api_rate_limited"
    assert len(calls) == client.budget.used == 1
    assert client.transient_retries == 0
    assert sleeps == []


def test_rate_limit_keeps_monitor_degraded():
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

@pytest.mark.parametrize("source", ["detail", "listing"])
def test_daily_quota_cooldown_survives_restart_without_api_requests(tmp_path, monkeypatch, capsys, source):
    import json
    import sys
    from types import SimpleNamespace
    from scout import procurement_chile as cli

    calls = []
    class FixtureClient:
        def __init__(self, *args, **kwargs):
            self.budget = SimpleNamespace(used=1)
            self.transient_retries = 0
        def changed_window(self, **kwargs):
            calls.append(kwargs)
            if source == "listing":
                raise ProcurementAPIError("api_rate_limited")
            return [], {"api_failures": {"api_rate_limited": 1},
                        "budget_exhausted": False, "malformed_details": 0}

    state = "state/public_procurement_chile/events.jsonl"
    report = "reports/public_procurement_chile/latest.json"
    store = cli.ProcurementStore(tmp_path / state)
    store.set_cursor("2026-06-01T00:00:00Z")
    before = store.latest_cursor()
    monkeypatch.setattr(cli, "ChileCompraClient", FixtureClient)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "_config", lambda: {"live_api_enabled": True,
        "limits": {"max_requests_per_run": 25, "max_list_pages": 2, "max_detail_requests": 20}})
    monkeypatch.setenv("CHILECOMPRA_TICKET", "fixture-only")
    monkeypatch.setattr(sys, "argv", ["procurement", "monitor", "--state", state, "--report", report])
    assert cli._main() == 2
    capsys.readouterr()
    reloaded = cli.ProcurementStore(tmp_path / state)
    assert reloaded.latest_cursor() == before
    from datetime import datetime, timezone, timedelta
    deadline = datetime.fromisoformat(reloaded.latest_rate_limit_cooldown())
    assert deadline > datetime.now(timezone.utc) + timedelta(hours=25)
    assert len(calls) == 1
    assert cli._main() == 2
    current = json.loads((tmp_path / report).read_text(encoding="utf-8"))
    assert current["outcome"] == "DEGRADED_QUOTA_COOLDOWN"
    assert current["diagnostics"]["requests_used"] == 0
    assert len(calls) == 1
    assert cli.ProcurementStore(tmp_path / state).latest_cursor() == before


def test_backfill_listing_429_records_shared_cooldown(tmp_path, monkeypatch):
    import sys
    from scout import procurement_chile as cli

    calls = []
    class FixtureClient:
        def __init__(self, *args, **kwargs):
            pass
        def historical_window(self, **kwargs):
            calls.append(kwargs)
            raise ProcurementAPIError("api_rate_limited")

    monkeypatch.setattr(cli, "ChileCompraClient", FixtureClient)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "_config", lambda: {"live_api_enabled": True,
        "limits": {"max_requests_per_run": 25, "max_list_pages": 2, "max_detail_requests": 20}})
    monkeypatch.setenv("CHILECOMPRA_TICKET", "fixture-only")
    monkeypatch.setattr(sys, "argv", ["procurement", "backfill", "--from",
        "2026-06-01T00:00:00Z", "--to", "2026-06-02T00:00:00Z"])
    with pytest.raises(ProcurementAPIError, match="api_rate_limited"):
        cli._main()
    assert cli.ProcurementStore(tmp_path / "state/public_procurement_chile/events.jsonl").latest_rate_limit_cooldown()
    assert cli._main() == 2
    assert len(calls) == 1


def test_expired_cooldown_allows_bounded_monitor_to_resume(tmp_path, monkeypatch):
    import sys
    from scout import procurement_chile as cli

    calls = []
    class FixtureClient:
        def __init__(self, *args, **kwargs):
            pass
        def changed_window(self, **kwargs):
            calls.append(kwargs)
            return [], {"api_failures": {}, "budget_exhausted": False, "malformed_details": 0}

    state = "state/public_procurement_chile/events.jsonl"
    cli.ProcurementStore(tmp_path / state).set_rate_limit_cooldown("2000-01-01T00:00:00Z")
    monkeypatch.setattr(cli, "ChileCompraClient", FixtureClient)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "_config", lambda: {"live_api_enabled": True,
        "limits": {"max_requests_per_run": 25, "max_list_pages": 2, "max_detail_requests": 20}})
    monkeypatch.setenv("CHILECOMPRA_TICKET", "fixture-only")
    monkeypatch.setattr(sys, "argv", ["procurement", "monitor", "--state", state])
    assert cli._main() == 0
    assert len(calls) == 1


def test_malformed_persisted_cooldown_fails_closed(tmp_path):
    import json
    from scout import procurement_chile as cli
    path = tmp_path / "events.jsonl"
    path.write_text(json.dumps({"event_id": "bad", "kind": "rate_limit_cooldown",
                                "retry_after": "bad"}) + "\n", encoding="utf-8")
    with pytest.raises(cli.ProcurementDataError, match="invalid_rate_limit_cooldown"):
        cli.ProcurementStore(path).latest_rate_limit_cooldown()
