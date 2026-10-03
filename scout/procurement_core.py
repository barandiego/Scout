"""Deterministic domain model for the Public Procurement Chile experiment."""
from __future__ import annotations
import hashlib, math
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION=1

class ProcurementError(RuntimeError): pass
class ProcurementDataError(ProcurementError): pass
class ProcurementAPIError(ProcurementError): pass

def D(v): return v if isinstance(v, dict) else {}
def L(v): return v if isinstance(v, list) else []
def S(v, n=4000): return v.encode("utf-8", errors="replace").decode("utf-8").strip()[:n] if isinstance(v, str) else ""
def N(v):
    if isinstance(v, bool) or type(v) not in (int,float): return None
    f=float(v); return f if math.isfinite(f) else None
def I(v): return v if type(v) is int else None
def B(v): return v if isinstance(v,bool) else None
def TS(v):
    s=S(v,100)
    if not s: return None
    try: d=datetime.fromisoformat(s.replace("Z","+00:00"))
    except ValueError: return None
    return d.isoformat() if d.tzinfo else None
def DT(v):
    d=datetime.fromisoformat(v.replace("Z","+00:00"))
    if d.tzinfo is None: raise ValueError("timestamp_requires_timezone")
    return d

def nonneg(v):
    x=N(v); return x if x is not None and x >= 0 else None
def nonneg_i(v):
    x=I(v); return x if x is not None and x >= 0 else None

STRICT=dict(strict=True, extra="forbid", allow_inf_nan=False)
class ProductLine(BaseModel):
    model_config=ConfigDict(**STRICT)
    product_code:str=""; name:str=""; description:str=""; quantity:float|None=None; unit:str=""
class QuoteProduct(BaseModel):
    model_config=ConfigDict(**STRICT)
    product_code:str=""; name:str=""; description:str=""; quantity:float|None=None
    unit_price_clp:float|None=Field(default=None,ge=0); line_total_clp:float|None=Field(default=None,ge=0)
class SupplierQuote(BaseModel):
    model_config=ConfigDict(**STRICT)
    supplier_rut:str=""; supplier_name:str=""; is_emt:bool|None=None; quote_id:int|None=None; active:bool|None=None
    created_at:str|None=None; valid_until:str|None=None
    net_clp:float|None=Field(default=None,ge=0); tax_clp:float|None=Field(default=None,ge=0)
    shipping_clp:float|None=Field(default=None,ge=0); total_clp:float|None=Field(default=None,ge=0)
    tax_name:str=""; tax_percent:float|None=Field(default=None,ge=0); description:str=""; inadmissibility_reason:str=""
    products:list[QuoteProduct]=Field(default_factory=list)
    @field_validator("created_at","valid_until")
    @classmethod
    def t(cls,v):
        if v is not None: DT(v)
        return v
class PurchaseOrderRef(BaseModel):
    model_config=ConfigDict(strict=True,extra="forbid")
    internal_id:int|None=None; id_oc:int|None=None; external_code:str=""; state:str=""
class ProcurementRecord(BaseModel):
    model_config=ConfigDict(**STRICT)
    schema_version:int=SCHEMA_VERSION; code:str=Field(min_length=1); name:str=""; description:str=""; status:str=""; call_number:int|None=None
    published_at:str; closes_at:str; first_call_closes_at:str|None=None; second_call_closes_at:str|None=None; last_changed_at:str
    buyer_name:str=""; buyer_rut:str=""; buying_unit:str=""; region_code:int|None=None; region_name:str=""
    delivery_address:str=""; delivery_days:int|None=Field(default=None,ge=0); budget_type:str=""; currency:str=""
    estimated_budget:float|None=Field(default=None,ge=0); available_budget:float|None=Field(default=None,ge=0); available_budget_clp:float|None=Field(default=None,ge=0)
    purchase_order:PurchaseOrderRef=Field(default_factory=PurchaseOrderRef); products:list[ProductLine]=Field(default_factory=list); quotes:list[SupplierQuote]=Field(default_factory=list)
    total_quotes_received:int|None=Field(default=None,ge=0); cancellation_reason:str=""; desert_reason:str=""; selection_reason:str=""; source_observed_at:str
    @field_validator("published_at","closes_at","first_call_closes_at","second_call_closes_at","last_changed_at","source_observed_at")
    @classmethod
    def t(cls,v):
        if v is not None: DT(v)
        return v
    @model_validator(mode="after")
    def chronology(self):
        if DT(self.closes_at)<DT(self.published_at): raise ValueError("close_before_publication")
        return self
    def digest(self):
        return hashlib.sha256(self.model_dump_json(exclude={"source_observed_at"}).encode()).hexdigest()
class TimedEvidence(BaseModel):
    model_config=ConfigDict(**STRICT)
    evidence_id:str=Field(min_length=1); kind:Literal["sourcing","competition","logistics","eligibility","regulatory","other"]
    source_url:str=Field(min_length=1); observed_at:str; claim:str=Field(min_length=1); price_clp:float|None=Field(default=None,ge=0); historical_price_exact:bool=False
    @field_validator("observed_at")
    @classmethod
    def t(cls,v): DT(v); return v
class EconomicsInputs(BaseModel):
    model_config=ConfigDict(**STRICT)
    bid_revenue_clp:float=Field(gt=0); acquisition_cost_clp:float=Field(ge=0); logistics_clp:float=Field(ge=0); taxes_and_fees_clp:float=Field(ge=0)
    other_required_costs_clp:float=Field(ge=0); expected_failure_cost_clp:float=Field(ge=0); capital_required_clp:float=Field(gt=0); capital_days:int=Field(gt=0); annual_financing_rate:float=Field(ge=0)
class EconomicsResult(BaseModel):
    model_config=ConfigDict(**STRICT)
    gross_spread_clp:float; financing_cost_clp:float; total_cost_clp:float; expected_net_profit_clp:float; net_margin:float
    return_on_deployed_capital:float; profit_per_capital_day:float
class DecisionPolicy(BaseModel):
    model_config=ConfigDict(**STRICT)
    min_net_margin:float=Field(ge=0); min_return_on_capital:float=Field(ge=0); max_capital_clp:float=Field(gt=0); max_capital_days:int=Field(gt=0)
    min_equivalence_confidence:float=Field(ge=0,le=1); min_evidence_confidence:float=Field(ge=0,le=1); require_historical_sourcing_price:bool=True
class CounterfactualCandidate(BaseModel):
    model_config=ConfigDict(**STRICT)
    procurement_code:str; decision_at:str; bid_deadline:str; hypothetical_bid_clp:float=Field(gt=0); maximum_acceptable_bid_clp:float=Field(gt=0)
    economics:EconomicsInputs; product_equivalence_confidence:float=Field(ge=0,le=1); evidence_confidence:float=Field(ge=0,le=1)
    competitive_price_estimate_clp:float|None=Field(default=None,gt=0); competitive_estimate_evidence_id:str=""
    delivery_feasible:bool|None=None; stock_confirmed:bool|None=None; eligible_supplier:bool|None=None; regulatory_clear:bool|None=None
    evidence:list[TimedEvidence]=Field(default_factory=list); major_risks:list[str]=Field(default_factory=list)
    @field_validator("decision_at","bid_deadline")
    @classmethod
    def t(cls,v): DT(v); return v
    @model_validator(mode="after")
    def bid_matches(self):
        if not math.isclose(self.hypothetical_bid_clp,self.economics.bid_revenue_clp,rel_tol=0,abs_tol=.01): raise ValueError("bid_economics_mismatch")
        return self
class ShadowDecision(BaseModel):
    model_config=ConfigDict(**STRICT)
    procurement_code:str; decision_at:str; decision:Literal["IGNORE","INVESTIGATE","WOULD_BID"]; hypothetical_bid_clp:float; maximum_acceptable_bid_clp:float
    expected_total_cost_clp:float; expected_profit_clp:float; expected_margin:float; confidence:float=Field(ge=0,le=1); capital_required_clp:float; capital_days:int; evidence_ids:list[str]; reasons:list[str]; major_risks:list[str]
class ObservedOutcome(BaseModel):
    model_config=ConfigDict(**STRICT)
    procurement_code:str; resolved_at:str; winning_total_clp:float|None=Field(default=None,ge=0); winning_supplier_rut:str=""; purchase_order_id:int|None=None; price_only_selection_verified:bool=False
    @field_validator("resolved_at")
    @classmethod
    def t(cls,v): DT(v); return v
class Reconciliation(BaseModel):
    model_config=ConfigDict(**STRICT)
    procurement_code:str; decision:Literal["IGNORE","INVESTIGATE","WOULD_BID"]; price_competitive:bool|None=None; would_have_won:bool|None=None; scoreability:str

def _payload(raw):
    if not isinstance(raw,dict) or raw.get("success") != "OK" or not isinstance(raw.get("payload"),dict): raise ProcurementDataError("api_response_not_success")
    return raw["payload"]
def normalize_detail(raw:dict[str,Any],*,observed_at:str)->ProcurementRecord:
    p=_payload(raw); f=D(p.get("fechas")); ent=D(p.get("entrega")); bud=D(p.get("presupuesto")); buy=D(p.get("institucion")); po=D(p.get("orden_compra"))
    code=S(p.get("codigo"),200); pub=TS(f.get("fecha_publicacion")); close=TS(f.get("fecha_cierre")); changed=TS(f.get("fecha_ultimo_cambio")) or pub
    obs=TS(observed_at)
    if not code: raise ProcurementDataError("missing_code")
    if not pub or not close or not changed or not obs: raise ProcurementDataError("missing_required_timestamps")
    products=[]
    for x in L(p.get("productos_solicitados")):
        x=D(x); products.append(ProductLine(product_code=S(x.get("codigo_producto"),200) or (str(x.get("codigo_producto")) if type(x.get("codigo_producto")) is int else ""),name=S(x.get("nombre")),description=S(x.get("descripcion")),quantity=nonneg(x.get("cantidad")),unit=S(x.get("unidad_medida"),200)))
    quotes=[]
    for x in L(p.get("proveedores_cotizando")):
        x=D(x); qps=[]
        for y in L(x.get("productos_cotizados")):
            y=D(y); qps.append(QuoteProduct(product_code=S(y.get("codigo_producto"),200) or (str(y.get("codigo_producto")) if type(y.get("codigo_producto")) is int else ""),name=S(y.get("nombre_producto")),description=S(y.get("descripcion")),quantity=nonneg(y.get("cantidad")),unit_price_clp=nonneg(y.get("precio_unitario")),line_total_clp=nonneg(y.get("monto_total_producto"))))
        quotes.append(SupplierQuote(supplier_rut=S(x.get("rut_proveedor"),100),supplier_name=S(x.get("razon_social")),is_emt=B(x.get("es_emt")),quote_id=nonneg_i(x.get("id_cotizacion")),active=B(x.get("activo")),created_at=TS(x.get("fecha_creacion")),valid_until=TS(x.get("fecha_vigencia")),net_clp=nonneg(x.get("valor_neto")),tax_clp=nonneg(x.get("total_impuesto")),shipping_clp=nonneg(x.get("monto_despacho")),total_clp=nonneg(x.get("monto_total")),tax_name=S(x.get("nombre_impuesto"),200),tax_percent=nonneg(x.get("porcentaje_impuesto")),description=S(x.get("descripcion_cotizacion")) or S(x.get("descripcion")),inadmissibility_reason=S(x.get("justificacion_inadmisibilidad")),products=qps))
    return ProcurementRecord(code=code,name=S(p.get("nombre")),description=S(p.get("descripcion")),status=S(D(p.get("estado")).get("codigo"),200).casefold(),call_number=I(D(p.get("convocatoria")).get("estado_convocatoria")),published_at=pub,closes_at=close,first_call_closes_at=TS(D(p.get("convocatoria")).get("fecha_cierre_primer_llamado")),second_call_closes_at=TS(D(p.get("convocatoria")).get("fecha_cierre_segundo_llamado")),last_changed_at=changed,buyer_name=S(buy.get("organismo_comprador")),buyer_rut=S(buy.get("rut"),100),buying_unit=S(buy.get("unidad_compra")),region_code=I(buy.get("region")),region_name=S(buy.get("nombre_region")),delivery_address=S(ent.get("direccion_entrega")),delivery_days=nonneg_i(ent.get("plazo_entrega_dias")),budget_type=S(bud.get("tipo_presupuesto"),200),currency=S(bud.get("moneda"),30),estimated_budget=nonneg(bud.get("presupuesto_estimado")),available_budget=nonneg(bud.get("monto_disponible")),available_budget_clp=nonneg(bud.get("monto_disponible_clp")),purchase_order=PurchaseOrderRef(internal_id=nonneg_i(po.get("id_orden_compra")),id_oc=nonneg_i(po.get("id_oc")),external_code=S(po.get("codigo_orden_compra"),200),state=S(po.get("estado_orden_compra"),200)),products=products,quotes=quotes,total_quotes_received=nonneg_i(D(p.get("resumen")).get("total_ofertas_recibidas")),cancellation_reason=S(D(p.get("motivos")).get("motivo_cancelacion")),desert_reason=S(D(p.get("motivos")).get("motivo_desierta")),selection_reason=S(D(p.get("motivos")).get("motivo_seleccion")),source_observed_at=obs)

def reconstructability_reasons(r:ProcurementRecord)->list[str]:
    out=[]
    if not r.description and not r.name: out.append("missing_requirement_description")
    if not r.products: out.append("missing_products")
    for x in r.products:
        if not x.name and not x.product_code: out.append("missing_product_identity")
        if x.quantity is None or x.quantity<=0: out.append("missing_quantity")
        if not x.unit: out.append("missing_unit")
    if not r.delivery_address: out.append("missing_delivery_location")
    if r.delivery_days is None: out.append("missing_delivery_deadline")
    if r.status in {"cerrada","proveedor_seleccionado","desierta","cancelada","oc_emitida"} and not any(q.total_clp is not None for q in r.quotes): out.append("no_observable_competitive_prices")
    return list(dict.fromkeys(out))
def phase1_survivors(records): return [r for r in records if not reconstructability_reasons(r)]
def compute_economics(x:EconomicsInputs)->EconomicsResult:
    financing=x.capital_required_clp*x.annual_financing_rate*x.capital_days/365
    cash=x.acquisition_cost_clp+x.logistics_clp+x.taxes_and_fees_clp+x.other_required_costs_clp+x.expected_failure_cost_clp
    total=cash+financing; profit=x.bid_revenue_clp-total
    return EconomicsResult(gross_spread_clp=x.bid_revenue_clp-x.acquisition_cost_clp,financing_cost_clp=financing,total_cost_clp=total,expected_net_profit_clp=profit,net_margin=profit/x.bid_revenue_clp,return_on_deployed_capital=profit/x.capital_required_clp,profit_per_capital_day=profit/(x.capital_required_clp*x.capital_days))
def stress_economics(x:EconomicsInputs,*,sourcing_error=0,logistics_error=0,revenue_error=0):
    return compute_economics(x.model_copy(update={"acquisition_cost_clp":x.acquisition_cost_clp*(1+sourcing_error),"logistics_clp":x.logistics_clp*(1+logistics_error),"bid_revenue_clp":x.bid_revenue_clp*(1+revenue_error)}))
def historical_decision(c:CounterfactualCandidate,p:DecisionPolicy)->ShadowDecision:
    if DT(c.decision_at)>DT(c.bid_deadline): raise ProcurementDataError("decision_after_deadline")
    for e in c.evidence:
        if DT(e.observed_at)>DT(c.decision_at): raise ProcurementDataError("historical_information_leakage")
    econ=compute_economics(c.economics); reasons=[]
    fatal=[]
    if c.hypothetical_bid_clp>c.maximum_acceptable_bid_clp: fatal.append("bid_above_maximum_acceptable")
    if econ.expected_net_profit_clp<=0: fatal.append("non_positive_expected_profit")
    if econ.net_margin<p.min_net_margin: fatal.append("insufficient_net_margin")
    if econ.return_on_deployed_capital<p.min_return_on_capital: fatal.append("insufficient_return_on_capital")
    if c.economics.capital_required_clp>p.max_capital_clp: fatal.append("working_capital_too_high")
    if c.economics.capital_days>p.max_capital_days: fatal.append("capital_days_too_high")
    if c.product_equivalence_confidence<p.min_equivalence_confidence: fatal.append("ambiguous_product_equivalence")
    if c.evidence_confidence<p.min_evidence_confidence: fatal.append("low_evidence_confidence")
    if c.delivery_feasible is False: fatal.append("delivery_infeasible")
    if c.stock_confirmed is False: fatal.append("stock_unavailable")
    if c.eligible_supplier is False: fatal.append("supplier_ineligible")
    if c.regulatory_clear is False: fatal.append("regulatory_uncertainty")
    sourcing=[e for e in c.evidence if e.kind=="sourcing" and e.price_clp is not None]
    comp=[e for e in c.evidence if e.kind=="competition"]
    if sourcing and not any(math.isclose(e.price_clp or -1,c.economics.acquisition_cost_clp,rel_tol=0,abs_tol=.01) for e in sourcing): reasons.append("sourcing_price_economics_mismatch")
    if not sourcing: reasons.append("missing_sourcing_price_evidence")
    elif p.require_historical_sourcing_price and not any(e.historical_price_exact for e in sourcing): reasons.append("historical_sourcing_price_unverified")
    matching_comp=[e for e in comp if e.evidence_id==c.competitive_estimate_evidence_id and e.price_clp is not None and c.competitive_price_estimate_clp is not None and math.isclose(e.price_clp,c.competitive_price_estimate_clp,rel_tol=0,abs_tol=.01)]
    if c.competitive_price_estimate_clp is None or not c.competitive_estimate_evidence_id or not matching_comp: reasons.append("missing_predeadline_competitive_evidence")
    if c.competitive_price_estimate_clp is not None and c.hypothetical_bid_clp>c.competitive_price_estimate_clp: fatal.append("bid_not_competitive_to_estimate")
    unknown=[]
    for value,reason in [(c.delivery_feasible,"delivery_feasibility_unknown"),(c.stock_confirmed,"stock_unknown"),(c.eligible_supplier,"supplier_eligibility_unknown"),(c.regulatory_clear,"regulatory_status_unknown")]:
        if value is None: unknown.append(reason)
    all_reasons=list(dict.fromkeys(fatal+reasons+unknown))
    decision="IGNORE" if fatal else "INVESTIGATE" if reasons or unknown else "WOULD_BID"
    return ShadowDecision(procurement_code=c.procurement_code,decision_at=c.decision_at,decision=decision,hypothetical_bid_clp=c.hypothetical_bid_clp,maximum_acceptable_bid_clp=c.maximum_acceptable_bid_clp,expected_total_cost_clp=econ.total_cost_clp,expected_profit_clp=econ.expected_net_profit_clp,expected_margin=econ.net_margin,confidence=c.evidence_confidence,capital_required_clp=c.economics.capital_required_clp,capital_days=c.economics.capital_days,evidence_ids=[e.evidence_id for e in c.evidence],reasons=all_reasons,major_risks=c.major_risks)
def reconcile(d:ShadowDecision,o:ObservedOutcome)->Reconciliation:
    if d.procurement_code!=o.procurement_code: raise ProcurementDataError("outcome_code_mismatch")
    if o.winning_total_clp is None: return Reconciliation(procurement_code=d.procurement_code,decision=d.decision,scoreability="winning_price_unavailable")
    pc=d.hypothetical_bid_clp<=o.winning_total_clp; won=pc if d.decision=="WOULD_BID" and o.price_only_selection_verified else None
    return Reconciliation(procurement_code=d.procurement_code,decision=d.decision,price_competitive=pc,would_have_won=won,scoreability="price_only_selection_verified" if o.price_only_selection_verified else "selection_not_price_only")

def phase1_report(records):
    survivors=phase1_survivors(records); reasons={}
    for r in records:
        for reason in reconstructability_reasons(r): reasons[reason]=reasons.get(reason,0)+1
    resolved=[r for r in records if r.status in {"cerrada","proveedor_seleccionado","desierta","cancelada","oc_emitida"}]
    return {"records":len(records),"resolved":len(resolved),"structurally_reconstructable":len(survivors),"with_observable_quote_totals":sum(any(q.total_clp is not None for q in r.quotes) for r in records),"with_purchase_order_indicator":sum(r.purchase_order.internal_id is not None for r in records),"rejection_reasons":dict(sorted(reasons.items()))}
