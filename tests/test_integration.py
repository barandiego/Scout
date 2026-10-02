import shutil
from scout import pipeline
from scout.models import Usage
from scout.runtime import AIResult

DISCOVERY={
'name':'Test industrial opportunity','type':'general','vertical':'general','geography':'Chile','discovery_lens':'energy_industrial',
'signal':'verified cost shift','what_changed':'input cost fell materially','why_now':'economics changed','thesis':'A real cost shift may create an economic opening.','value_capture_mechanism':'Own or distribute the newly economic product and capture gross margin from customers.',
'evidence':[{'title':'Primary','url':'https://primary.example/a','source_type':'primary','claim':'cost shift'},{'title':'Independent','url':'https://independent.example/b','source_type':'independent','claim':'market context'}],
'contrary_evidence':[],'evidence_confidence':0.8,'capital_required':'low','diego_hours_initial':'2h','diego_hours_ongoing':'low','ai_leverage':'high','time_horizon':'months','major_risks':['competition'],'unknowns':['unit economics'],'falsification_conditions':['cost advantage reverses'],'real':True,'actionable':True,'participation_path':'Validate buyers and unit economics before any capital allocation.','material_update':False,'update_summary':''}

class FakeAI:
    def __init__(self,pricing): pass
    def json_research(self,**kw):
        ins=kw['instructions']
        if 'Scout Discovery' in ins:
            return AIResult({'candidates':[DISCOVERY]},Usage(model=kw['model'],estimated_cost_usd=.01),{'https://primary.example/a','https://independent.example/b'})
        if 'adversarial' in ins:
            return AIResult({'fatal':False,'critic_case':'No fatal contradiction found.','contrary_evidence':[],'unknowns':[],'falsification_conditions':[],'evidence_confidence':.75},Usage(model=kw['model'],estimated_cost_usd=.01),{'https://critic.example/c'})
        return AIResult({'status':'survived','vertical_fatal':False,'decision_reason':'Evidence supports HQ review.','judgment_confidence':.7,'major_risks':['competition'],'unknowns':['unit economics']},Usage(model=kw['model'],estimated_cost_usd=.01),set())

def test_full_cycle_without_network(tmp_path,monkeypatch):
    source_root=pipeline.ROOT
    shutil.copytree(source_root/'config',tmp_path/'config'); (tmp_path/'state').mkdir(); (tmp_path/'reports').mkdir()
    monkeypatch.setattr(pipeline,'ROOT',tmp_path); monkeypatch.setattr(pipeline,'AIClient',FakeAI)
    rec=pipeline.run_cycle(); assert rec.ok; assert rec.survivors==1; assert rec.errors==0; assert rec.cost_usd==.03
    assert (tmp_path/'state'/'survivors.jsonl').exists(); assert 'Test industrial opportunity' in (tmp_path/'reports'/'latest.md').read_text()
