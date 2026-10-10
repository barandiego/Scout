"""Offline-first Chile Compra Ágil historical experiment.

This facade is deliberately isolated from Scout's paid V0 cycle. It can read and
score procurement evidence; it cannot quote, buy, contact, register, invoice or pay.
"""
from __future__ import annotations
import argparse, json, os
from datetime import datetime, timezone, timedelta
from pathlib import Path
import yaml
from .procurement_core import *  # noqa: F403 - explicit experiment facade
from .procurement_io import ChileCompraClient, ProcurementStore, RequestBudget
from .state import atomic_write

ROOT=Path(__file__).resolve().parents[1]
TRANSIENT_MONITOR_ERRORS={"api_http_502","api_http_503","api_http_504","api_transport_error","api_rate_limited"}


def monitor_health(diag: dict) -> tuple[bool, str]:
    """Partial source windows are not a healthy, complete monitor run."""
    if diag.get("api_failures"):
        return False, "DEGRADED_API_ERRORS"
    if diag.get("budget_exhausted"):
        return False, "DEGRADED_INCOMPLETE_REQUEST_BUDGET"
    return True, "COMPLETE"


def _config():
    with (ROOT/"config"/"experiments"/"public_procurement_chile.yaml").open(encoding="utf-8") as h:
        return yaml.safe_load(h) or {}

def _main():
    p=argparse.ArgumentParser(description="Offline-first Public Procurement Chile experiment")
    sp=p.add_subparsers(dest="cmd",required=True)
    v=sp.add_parser("validate-fixture"); v.add_argument("path")
    b=sp.add_parser("backfill"); b.add_argument("--from",dest="start",required=True); b.add_argument("--to",dest="end",required=True); b.add_argument("--state",default="state/public_procurement_chile/events.jsonl")
    m=sp.add_parser("monitor"); m.add_argument("--state",default="state/public_procurement_chile/events.jsonl"); m.add_argument("--report",default="reports/public_procurement_chile/latest.json"); m.add_argument("--lookback-hours",type=int,default=6)
    a=p.parse_args()
    if a.cmd=="validate-fixture":
        r=normalize_detail(json.loads(Path(a.path).read_text(encoding="utf-8")),observed_at=datetime.now(timezone.utc).isoformat())  # noqa: F405
        print(json.dumps({"ok":True,"code":r.code,"reconstructability_reasons":reconstructability_reasons(r)},indent=2)); return 0  # noqa: F405
    cfg=_config()
    if not cfg.get("live_api_enabled"): raise ProcurementAPIError("live_api_disabled_in_config")  # noqa: F405
    lim=D(cfg.get("limits"))  # noqa: F405
    client=ChileCompraClient(os.environ.get("CHILECOMPRA_TICKET","").strip(),request_limit=int(lim["max_requests_per_run"]))
    observed=datetime.now(timezone.utc).replace(microsecond=0)
    observed_iso=observed.isoformat().replace("+00:00","Z")
    st=ProcurementStore(ROOT/a.state)
    if a.cmd=="backfill":
        records,diag=client.historical_window(published_from=a.start,published_to=a.end,observed_at=observed_iso,max_pages=int(lim["max_list_pages"]),max_details=int(lim["max_detail_requests"]),states=["cerrada","proveedor_seleccionado","desierta","cancelada","oc_emitida"])
        inserted=sum(st.add_history(r) for r in records)
        print(json.dumps({"ok":True,"inserted":inserted,"diagnostics":diag,"phase1":phase1_report(records)},indent=2)); return 0  # noqa: F405
    if a.lookback_hours<1 or a.lookback_hours>24: raise ProcurementAPIError("invalid_monitor_lookback")  # noqa: F405
    cursor=st.latest_cursor()
    changed_from=cursor or (observed-timedelta(hours=a.lookback_hours)).isoformat().replace("+00:00","Z")
    try:
        records,diag=client.changed_window(changed_from=changed_from,changed_to=observed_iso,observed_at=observed_iso,max_pages=int(lim["max_list_pages"]),max_details=int(lim["max_detail_requests"]))
    except ProcurementAPIError as exc:  # noqa: F405
        reason=str(exc)
        if reason not in TRANSIENT_MONITOR_ERRORS: raise
        report={
            "schema_version":1,"generated_at":observed_iso,"window":{"changed_from":changed_from,"changed_to":observed_iso},
            "ok":False,"outcome":"DEGRADED_TRANSIENT_API","inserted_history":0,
            "diagnostics":{"api_failures":{reason:1},"requests_used":client.budget.used,"transient_retries":client.transient_retries},
            "phase1":{"records":0,"resolved":0,"structurally_reconstructable":0,"with_observable_quote_totals":0,"with_purchase_order_indicator":0,"rejection_reasons":{}},
            "active_structurally_reconstructable_count":0,"active_candidates":[],
            "note":"Transient ChileCompra/API availability failure after bounded retries. Cursor was not advanced; next scheduled run may retry safely."
        }
        atomic_write(ROOT/a.report,json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n")
        print(json.dumps(report,ensure_ascii=False,indent=2))
        return 2
    inserted=sum(st.add_history(r) for r in records)
    if not diag.get("budget_exhausted") and not diag.get("api_failures"): st.set_cursor(observed_iso)
    candidates=[r for r in records if r.status=="publicada" and not reconstructability_reasons(r)]  # noqa: F405
    cap=int(D(cfg.get("monitor")).get("max_report_candidates",20))  # noqa: F405
    healthy, outcome = monitor_health(diag)
    report={
        "schema_version":1,"generated_at":observed_iso,"window":{"changed_from":changed_from,"changed_to":observed_iso},
        "ok":healthy,"outcome":outcome,"inserted_history":inserted,"diagnostics":diag,"phase1":phase1_report(records),  # noqa: F405
        "active_structurally_reconstructable_count":len(candidates),
        "active_candidates":[{"code":r.code,"name":r.name[:240],"buyer":r.buyer_name[:240],"region":r.region_name[:120],"closes_at":r.closes_at,"available_budget_clp":r.available_budget_clp,"estimated_budget":r.estimated_budget,"products":len(r.products)} for r in candidates[:cap]],
        "note":"Research/watch output only. No sourcing-cost or profitability claim is made."
    }
    atomic_write(ROOT/a.report,json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if healthy else 2

if __name__=="__main__": raise SystemExit(_main())
