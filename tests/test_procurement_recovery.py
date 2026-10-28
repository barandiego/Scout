import json
import sys
from pathlib import Path
import pytest
from scout.procurement_io import ProcurementStore
from scout.procurement_recovery import next_window, record_window
from scout import procurement_chile as cli

START = "2026-10-11T00:00:00Z"
END = "2026-10-11T00:00:04Z"

def test_persistent_splits_overlap_and_never_advance_cursor(tmp_path):
    path = tmp_path / "events.jsonl"
    store = ProcurementStore(path)
    store.set_cursor("2026-10-10T00:00:00Z")
    plan, a, b = next_window(store, START, END)
    record_window(store, plan, a, b, "split")
    store = ProcurementStore(path)
    plan, a, b = next_window(store, START, END)
    assert (a, b) == (START, "2026-10-11T00:00:02Z")
    record_window(store, plan, a, b, "observed")
    store = ProcurementStore(path)
    plan, a, b = next_window(store, START, END)
    assert (a, b) == ("2026-10-11T00:00:02Z", END)
    record_window(store, plan, a, b, "observed")
    store = ProcurementStore(path)
    assert next_window(store, START, END)[1:] == (None, None)
    assert store.latest_cursor().startswith("2026-10-10")

def test_partial_window_is_durable_and_only_one_window_per_run(tmp_path, monkeypatch, capsys):
    calls = []
    class Client:
        def __init__(self, ticket, *, request_limit):
            assert ticket == "fixture"
        def changed_window(self, **kwargs):
            calls.append((kwargs["changed_from"], kwargs["changed_to"]))
            return [], {"detail_cap_exhausted": len(calls) == 1,
                        "api_failures": {}, "requests_used": 1}
    monkeypatch.setattr(cli, "ChileCompraClient", Client)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "_config", lambda: {"live_api_enabled": True,
        "limits": {"max_requests_per_run": 3, "max_list_pages": 1,
                   "max_detail_requests": 1}})
    monkeypatch.setenv("CHILECOMPRA_TICKET", "fixture")
    monkeypatch.setattr(sys, "argv", ["procurement", "recover", "--from", START,
        "--to", END, "--state", "events.jsonl"])
    assert cli._main() == 2
    first = json.loads(capsys.readouterr().out)
    assert first["action"] == "split" and first["cursor_advanced"] is False
    assert len(calls) == 1
    assert cli._main() == 2
    second = json.loads(capsys.readouterr().out)
    assert second["action"] == "observed" and second["ok"] is False
    assert calls[1] == (START, "2026-10-11T00:00:02Z")
    assert ProcurementStore(tmp_path / "events.jsonl").latest_cursor() is None

def test_rate_limit_or_malformed_is_retried_not_split(tmp_path, monkeypatch, capsys):
    class Client:
        def __init__(self, ticket, *, request_limit): pass
        def changed_window(self, **kwargs):
            return [], {"detail_cap_exhausted": True, "malformed_details": 1,
                        "api_failures": {}, "requests_used": 1}
    monkeypatch.setattr(cli, "ChileCompraClient", Client)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "_config", lambda: {"live_api_enabled": True,
        "limits": {"max_requests_per_run": 3, "max_list_pages": 1,
                   "max_detail_requests": 1}})
    monkeypatch.setenv("CHILECOMPRA_TICKET", "fixture")
    monkeypatch.setattr(sys, "argv", ["procurement", "recover", "--from", START,
        "--to", END, "--state", "events.jsonl"])
    assert cli._main() == 2
    assert json.loads(capsys.readouterr().out)["action"] == "retry_required"
    assert next_window(ProcurementStore(tmp_path / "events.jsonl"), START, END)[1:] == (START, END)
def test_partial_record_survives_retry_without_duplicate(tmp_path, monkeypatch, capsys):
    from scout.procurement_chile import normalize_detail
    raw = json.loads((Path(__file__).parent / "fixtures" / "compra_agil_detail_documented.json").read_text(encoding="utf-8"))
    record = normalize_detail(raw, observed_at="2026-06-04T12:00:00+00:00")
    class Client:
        def __init__(self, ticket, *, request_limit): pass
        def changed_window(self, **kwargs):
            return [record], {"malformed_details": 1, "api_failures": {}, "requests_used": 1}
    monkeypatch.setattr(cli, "ChileCompraClient", Client)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "_config", lambda: {"live_api_enabled": True,
        "limits": {"max_requests_per_run": 3, "max_list_pages": 1, "max_detail_requests": 1}})
    monkeypatch.setenv("CHILECOMPRA_TICKET", "fixture")
    monkeypatch.setattr(sys, "argv", ["procurement", "recover", "--from", START,
        "--to", END, "--state", "events.jsonl"])
    for expected in (1, 0):
        assert cli._main() == 2
        assert json.loads(capsys.readouterr().out)["inserted_history"] == expected
    events = ProcurementStore(tmp_path / "events.jsonl").events
    assert len([e for e in events if e["kind"] == "history_snapshot"]) == 1
    assert not [e for e in events if e["kind"] == "recovery_window"]

def test_canonical_monitor_state_cannot_be_used(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "_config", lambda: {"live_api_enabled": True,
        "limits": {"max_requests_per_run": 3, "max_list_pages": 1, "max_detail_requests": 1}})
    monkeypatch.setenv("CHILECOMPRA_TICKET", "fixture")
    monkeypatch.setattr(sys, "argv", ["procurement", "recover", "--from", START,
        "--to", END, "--state", "state/public_procurement_chile/events.jsonl"])
    with pytest.raises(cli.ProcurementAPIError, match="recovery_requires_isolated_state"):
        cli._main()
def test_real_http_recovery_is_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "_config", lambda: {"live_api_enabled": True,
        "limits": {"max_requests_per_run": 3, "max_list_pages": 1, "max_detail_requests": 1}})
    monkeypatch.setenv("CHILECOMPRA_TICKET", "fixture")
    monkeypatch.setattr(sys, "argv", ["procurement", "recover", "--from", START,
        "--to", END, "--state", "recovery.jsonl"])
    with pytest.raises(cli.ProcurementAPIError, match="recovery_live_not_supported"):
        cli._main()