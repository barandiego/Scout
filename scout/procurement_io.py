"""Bounded read-only ChileCompra adapter and isolated procurement state store."""
from __future__ import annotations
import json
import time
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from .state import atomic_write, read_jsonl
from .procurement_core import D,L,S,TS,DT,nonneg_i,_payload,normalize_detail,ProcurementAPIError,ProcurementDataError

BASE_URL="https://api2.mercadopublico.cl"

def _detail_shape(raw):
    payload=D(raw.get("payload")) if isinstance(raw,dict) else {}
    fechas=D(payload.get("fechas"))
    date_shape={}
    for key in ("fecha_publicacion","fecha_cierre","fecha_ultimo_cambio"):
        value=fechas.get(key)
        item={"present":key in fechas,"type":type(value).__name__}
        if isinstance(value,str):
            try:
                parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
                item["parseable_iso"]=True
                item["timezone_aware"]=parsed.tzinfo is not None
            except ValueError:
                item["parseable_iso"]=False
                item["timezone_aware"]=False
        date_shape[key]=item
    return {"payload_keys":sorted(str(k) for k in payload.keys()),"fechas_keys":sorted(str(k) for k in fechas.keys()),"date_shape":date_shape}

@dataclass
class RequestBudget:
    limit:int; used:int=0
    def __post_init__(self):
        if type(self.limit) is not int or self.limit<=0: raise ProcurementAPIError("invalid_request_budget")
    def spend(self):
        if self.used>=self.limit: raise ProcurementAPIError("request_budget_exhausted")
        self.used+=1

def _transport(url,headers,timeout):
    try:
        with urlopen(Request(url,headers=headers,method="GET"),timeout=timeout) as r:
            raw=r.read(5_000_001)
            if len(raw)>5_000_000: raise ProcurementAPIError("response_too_large")
            data=json.loads(raw.decode("utf-8"))
            if not isinstance(data,dict): raise ProcurementAPIError("invalid_api_json")
            return data
    except HTTPError as e: raise ProcurementAPIError("api_rate_limited" if e.code==429 else f"api_http_{e.code}") from None
    except (URLError,TimeoutError): raise ProcurementAPIError("api_transport_error") from None
    except (UnicodeDecodeError,json.JSONDecodeError): raise ProcurementAPIError("invalid_api_json") from None
class ChileCompraClient:
    def __init__(self,ticket:str,*,request_limit:int,timeout:float=40,transport:Callable|None=None,base_url:str=BASE_URL,retry_limit:int=2,retry_backoff_seconds:float=1.0,sleep_fn:Callable|None=None):
        if not ticket: raise ProcurementAPIError("missing_ticket")
        if type(retry_limit) is not int or retry_limit<0 or retry_limit>5: raise ProcurementAPIError("invalid_retry_limit")
        if not isinstance(retry_backoff_seconds,(int,float)) or retry_backoff_seconds<0: raise ProcurementAPIError("invalid_retry_backoff")
        self.ticket=ticket; self.budget=RequestBudget(request_limit); self.timeout=timeout; self.transport=transport or _transport; self.base_url=base_url.rstrip("/")
        self.retry_limit=retry_limit; self.retry_backoff_seconds=float(retry_backoff_seconds); self.sleep_fn=sleep_fn or time.sleep; self.transient_retries=0
    def _get(self,path,params=None):
        q=("?"+urlencode(params,doseq=True)) if params else ""
        transient={"api_http_502","api_http_503","api_http_504","api_transport_error"}
        for attempt in range(self.retry_limit+1):
            self.budget.spend()
            try:
                return self.transport(self.base_url+path+q,{"ticket":self.ticket},self.timeout)
            except ProcurementAPIError as e:
                reason=str(e)
                can_retry=reason in transient and attempt<self.retry_limit and self.budget.used<self.budget.limit
                if not can_retry: raise
                self.transient_retries+=1
                self.sleep_fn(self.retry_backoff_seconds*(2**attempt))
        raise ProcurementAPIError("unreachable_retry_state")
    def list_page(self,*,published_from=None,published_to=None,changed_from=None,changed_to=None,page=1,page_size=15,states=None,region=None,query=None):
        if type(page) is not int or page<1 or type(page_size) is not int or not 1<=page_size<=50: raise ProcurementAPIError("invalid_pagination")
        if (published_from or published_to) and (changed_from or changed_to): raise ProcurementAPIError("mixed_publication_and_change_windows")
        if region is not None and (type(region) is not int or not 1<=region<=16): raise ProcurementAPIError("invalid_region")
        allowed={"publicada","cerrada","proveedor_seleccionado","desierta","cancelada","oc_emitida"}
        if states and any(x not in allowed for x in states): raise ProcurementAPIError("invalid_state_filter")
        p={"numero_pagina":page,"tamano_pagina":page_size}
        for k,v in [("publicado_desde",published_from),("publicado_hasta",published_to),("cambio_desde",changed_from),("cambio_hasta",changed_to),("region",region),("q",query)]:
            if v is not None: p[k]=v
        if states: p["estado"]=",".join(states)
        if changed_from or changed_to: p["ordenar_por"]="FechaUltimaModificacion"
        return self._get("/v2/compra-agil",p)
    def detail(self,code):
        if not S(code,200): raise ProcurementAPIError("invalid_procurement_code")
        return self._get("/v2/compra-agil/"+quote(code,safe=""))
    def historical_window(self,*,published_from,published_to,observed_at,max_pages,max_details,states=None):
        if type(max_pages) is not int or max_pages<=0 or type(max_details) is not int or max_details<=0: raise ProcurementAPIError("invalid_history_caps")
        records=[]; codes=set(); duplicates=malformed=pages=detail_attempts=0; malformed_reasons={}; malformed_samples=[]; api_failures={}; budget_exhausted=False; rate_limited=False
        for page in range(1,max_pages+1):
            payload=D(_payload(self.list_page(published_from=published_from,published_to=published_to,page=page,page_size=50,states=states)))
            items=L(payload.get("items")); pag=D(payload.get("paginacion")); pages+=1
            for item in items:
                code=S(D(item).get("codigo"),200)
                if not code: continue
                if code in codes: duplicates+=1; continue
                codes.add(code)
                if detail_attempts>=max_details or self.budget.used>=self.budget.limit:
                    budget_exhausted=self.budget.used>=self.budget.limit
                    break
                detail_attempts+=1
                try:
                    raw=self.detail(code)
                except ProcurementAPIError as e:
                    reason=str(e) or e.__class__.__name__
                    api_failures[reason]=api_failures.get(reason,0)+1
                    if reason=="api_rate_limited":
                        rate_limited=True; budget_exhausted=self.budget.used>=self.budget.limit
                        break
                    if reason=="request_budget_exhausted" or self.budget.used>=self.budget.limit:
                        budget_exhausted=True
                        break
                    continue
                try: records.append(normalize_detail(raw,observed_at=observed_at))
                except ProcurementDataError as e:
                    malformed+=1
                    reason=str(e) or e.__class__.__name__
                    malformed_reasons[reason]=malformed_reasons.get(reason,0)+1
                    if len(malformed_samples)<1: malformed_samples.append({"code":code,"reason":reason,**_detail_shape(raw)})
            if detail_attempts>=max_details or budget_exhausted or rate_limited: break
            total=nonneg_i(pag.get("total_paginas")); current=nonneg_i(pag.get("numero_pagina"))
            if total is None or current is None or current>=total: break
        return records,{"pages_fetched":pages,"detail_attempts":detail_attempts,"details_fetched":len(records),"duplicate_listings":duplicates,"malformed_details":malformed,"malformed_reasons":dict(sorted(malformed_reasons.items())),"malformed_samples":malformed_samples,"api_failures":dict(sorted(api_failures.items())),"transient_retries":self.transient_retries,"budget_exhausted":budget_exhausted,"requests_used":self.budget.used}

    def changed_window(self,*,changed_from,changed_to,observed_at,max_pages,max_details,states=None):
        if type(max_pages) is not int or max_pages<=0 or type(max_details) is not int or max_details<=0: raise ProcurementAPIError("invalid_change_caps")
        records=[]; codes=set(); duplicates=malformed=pages=detail_attempts=0; malformed_reasons={}; malformed_samples=[]; api_failures={}; budget_exhausted=False; rate_limited=False
        detail_cap_exhausted=False; pagination_incomplete=False; pagination_invalid=False; invalid_listing_items=0
        for page in range(1,max_pages+1):
            payload=D(_payload(self.list_page(changed_from=changed_from,changed_to=changed_to,page=page,page_size=50,states=states)))
            raw_items=payload.get("items")
            if not isinstance(raw_items,list): invalid_listing_items+=1
            items=L(raw_items); pag=D(payload.get("paginacion")); pages+=1
            for item in items:
                code=S(D(item).get("codigo"),200)
                if not code:
                    invalid_listing_items+=1
                    continue
                if code in codes: duplicates+=1; continue
                codes.add(code)
                if detail_attempts>=max_details:
                    detail_cap_exhausted=True
                    break
                if self.budget.used>=self.budget.limit:
                    budget_exhausted=True
                    break
                detail_attempts+=1
                try:
                    raw=self.detail(code)
                except ProcurementAPIError as e:
                    reason=str(e) or e.__class__.__name__
                    api_failures[reason]=api_failures.get(reason,0)+1
                    if reason=="api_rate_limited":
                        rate_limited=True; budget_exhausted=self.budget.used>=self.budget.limit
                        break
                    if reason=="request_budget_exhausted" or self.budget.used>=self.budget.limit:
                        budget_exhausted=True
                        break
                    continue
                try: records.append(normalize_detail(raw,observed_at=observed_at))
                except ProcurementDataError as e:
                    malformed+=1
                    reason=str(e) or e.__class__.__name__
                    malformed_reasons[reason]=malformed_reasons.get(reason,0)+1
                    if len(malformed_samples)<1: malformed_samples.append({"code":code,"reason":reason,**_detail_shape(raw)})
            if detail_cap_exhausted or budget_exhausted or rate_limited: break
            total=nonneg_i(pag.get("total_paginas")); current=nonneg_i(pag.get("numero_pagina"))
            if total is None or current is None or total<1 or current!=page or current>total:
                pagination_invalid=True
                break
            if current>=total: break
            if detail_attempts>=max_details:
                detail_cap_exhausted=True
                break
            if page==max_pages:
                pagination_incomplete=True
                break
        return records,{"pages_fetched":pages,"detail_attempts":detail_attempts,"details_fetched":len(records),"duplicate_listings":duplicates,"malformed_details":malformed,"malformed_reasons":dict(sorted(malformed_reasons.items())),"malformed_samples":malformed_samples,"api_failures":dict(sorted(api_failures.items())),"transient_retries":self.transient_retries,"budget_exhausted":budget_exhausted,"requests_used":self.budget.used,"detail_cap_exhausted":detail_cap_exhausted,"pagination_incomplete":pagination_incomplete,"pagination_invalid":pagination_invalid,"invalid_listing_items":invalid_listing_items}

class ProcurementStore:
    def __init__(self,path:Path):
        self.path=path; self.events=read_jsonl(path); seen={}
        for e in self.events:
            eid=e.get("event_id") if isinstance(e,dict) else None
            if not isinstance(eid,str) or not eid or not isinstance(e.get("kind"),str): raise ProcurementDataError("invalid_procurement_state")
            if eid in seen and seen[eid]!=e: raise ProcurementDataError("conflicting_procurement_event")
            seen[eid]=e
    def _append(self,e):
        for old in self.events:
            if old["event_id"]==e["event_id"]:
                if old!=e: raise ProcurementDataError("immutable_event_conflict")
                return False
        self.events.append(e); atomic_write(self.path,"".join(json.dumps(x,ensure_ascii=False,sort_keys=True,allow_nan=False)+"\n" for x in self.events)); return True
    def add_history(self,r): return self._append({"event_id":f"history:{r.code}:{r.last_changed_at}:{r.digest()[:16]}","kind":"history_snapshot","record":r.model_dump()})
    def add_shadow_decision(self,d): return self._append({"event_id":f"shadow:{d.procurement_code}:{d.decision_at}","kind":"shadow_decision","decision":d.model_dump()})
    def add_outcome(self,o): return self._append({"event_id":f"outcome:{o.procurement_code}:{o.resolved_at}","kind":"outcome","outcome":o.model_dump()})
    def latest_cursor(self):
        prior=[e["changed_through"] for e in self.events if e.get("kind")=="sync_cursor"]
        return max(prior,key=DT) if prior else None
    def set_cursor(self,changed_through):
        cur=TS(changed_through)
        if not cur: raise ProcurementDataError("invalid_sync_cursor")
        prior=[e["changed_through"] for e in self.events if e.get("kind")=="sync_cursor"]
        if prior and DT(cur)<max(DT(x) for x in prior): raise ProcurementDataError("sync_cursor_regression")
        return self._append({"event_id":"cursor:"+cur,"kind":"sync_cursor","changed_through":cur})
