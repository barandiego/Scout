"""Offline-first Chile Compra Ágil historical experiment.

This facade is deliberately isolated from Scout's paid V0 cycle. It can read and
score procurement evidence; it cannot quote, buy, contact, register, invoice or pay.
"""
from __future__ import annotations
import argparse, json, os
from datetime import datetime, timezone
from pathlib import Path
import yaml
from .procurement_core import *  # noqa: F403 - explicit experiment facade
from .procurement_io import ChileCompraClient, ProcurementStore, RequestBudget

ROOT=Path(__file__).resolve().parents[1]

def _config():
    with (ROOT/"config"/"experiments"/"public_procurement_chile.yaml").open(encoding="utf-8") as h:
        return yaml.safe_load(h) or {}

def _main():
    p=argparse.ArgumentParser(description="Offline-first Public Procurement Chile experiment")
    sp=p.add_subparsers(dest="cmd",required=True)
    v=sp.add_parser("validate-fixture"); v.add_argument("path")
    b=sp.add_parser("backfill"); b.add_argument("--from",dest="start",required=True); b.add_argument("--to",dest="end",required=True); b.add_argument("--state",default="state/public_procurement_chile/events.jsonl")
    a=p.parse_args()
    if a.cmd=="validate-fixture":
        r=normalize_detail(json.loads(Path(a.path).read_text(encoding="utf-8")),observed_at=datetime.now(timezone.utc).isoformat())  # noqa: F405
        print(json.dumps({"ok":True,"code":r.code,"reconstructability_reasons":reconstructability_reasons(r)},indent=2)); return 0  # noqa: F405
    cfg=_config()
    if not cfg.get("live_api_enabled"): raise ProcurementAPIError("live_api_disabled_in_config")  # noqa: F405
    lim=D(cfg.get("limits"))  # noqa: F405
    c=ChileCompraClient(os.environ.get("CHILECOMPRA_TICKET","").strip(),request_limit=int(lim["max_requests_per_manual_run"]))
    records,diag=c.historical_window(published_from=a.start,published_to=a.end,observed_at=datetime.now(timezone.utc).isoformat(),max_pages=int(lim["max_list_pages"]),max_details=int(lim["max_detail_requests"]),states=["cerrada","proveedor_seleccionado","desierta","cancelada"])
    st=ProcurementStore(ROOT/a.state); inserted=sum(st.add_history(r) for r in records)
    print(json.dumps({"ok":True,"inserted":inserted,"diagnostics":diag,"phase1":phase1_report(records)},indent=2)); return 0  # noqa: F405

if __name__=="__main__": raise SystemExit(_main())
