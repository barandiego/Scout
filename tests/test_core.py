from scout.pipeline import Budget, hard_gate_reasons, is_duplicate, normalize_candidate, similarity
from scout.models import Usage

def good(name='Example'):
    return normalize_candidate({
        'name':name,'type':'public_markets','vertical':'public_markets','geography':'Canada','discovery_lens':'public_markets',
        'signal':'verified filing changed financing','what_changed':'new committed financing','why_now':'valuation may not reflect change',
        'thesis':'Financing may reduce dilution risk and change risked per-share value.',
        'value_capture_mechanism':'Potential public-market repricing if risk falls faster than valuation rises.',
        'evidence':[{'title':'Filing','url':'https://issuer.example/a','source_type':'primary','claim':'financing'},{'title':'Independent','url':'https://news.example/b','source_type':'independent','claim':'context'}],
        'evidence_confidence':0.8,'real':True,'actionable':True,'participation_path':'Research the listed security through a supported brokerage before any decision.'})

def test_good_candidate_passes_hard_gates(): assert hard_gate_reasons(good())==[]
def test_fake_candidate_fails():
    op=normalize_candidate({'name':'fake','value_capture_mechanism':'','real':False,'actionable':False,'evidence':[]})
    assert len(hard_gate_reasons(op))>=4
def test_duplicate_detection():
    a,b=good('Aclara financing thesis'),good('Aclara financing thesis'); assert similarity(a,b)==1.0; assert is_duplicate(b,[a],0.72)
def test_material_update_can_reopen_duplicate():
    a=good('Aclara financing thesis'); b=good('Aclara financing thesis'); b.material_update=True; b.update_summary='New committed financing materially changes dilution risk.'; b.evidence.append(type(b.evidence[0])(title='New filing',url='https://issuer.example/new',source_type='primary',claim='commitment'))
    assert not is_duplicate(b,[a],0.72); assert b.opportunity_id==a.opportunity_id
def test_duplicate_evidence_url_does_not_pass():
    op=good(); op.evidence[1].url=op.evidence[0].url; assert 'insufficient_unique_evidence' in hard_gate_reasons(op)
def test_budget_stops_future_stages():
    b=Budget(.08,.25,0); assert b.can_spend(.03); b.add(Usage(model='x',estimated_cost_usd=.07)); assert not b.can_spend(.02)
