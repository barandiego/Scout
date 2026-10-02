import json
import pytest
from scout import pipeline, state
from scout.models import RunRecord, Opportunity
from scout.state import Store, StateError, atomic_write, exclusive_writer
from test_integration import harness, candidate, SOURCES, CRITIC, JUDGE


def test_historic_state_is_parseable_consistent_and_cost_preserved():
    store=Store(pipeline.ROOT)
    # Repo's four persisted failed runs: #1/#2 stopped before Scout ran.
    assert len(store.legacy_runs)==4
    assert len({r['run_id'] for r in store.legacy_runs})==4
    assert sum(r['cost_usd'] for r in store.legacy_runs)==pytest.approx(.030456)
    assert all(r['survivors']==r['normalized_candidates']==0 for r in store.legacy_runs)


@pytest.mark.parametrize('line', ['{broken\n', 'null\n','[]\n','{"cost_usd":NaN}\n'])
def test_corrupt_legacy_line_stops_before_provider(tmp_path,monkeypatch,harness,line):
    path=tmp_path/'state/runs.jsonl';path.parent.mkdir();path.write_text(line)
    calls=[]
    monkeypatch.setattr(pipeline,'AIClient',lambda _:calls.append('created'))
    rec=pipeline.run_cycle()
    assert not rec.ok and rec.outcome=='FAILED_INFRASTRUCTURE' and not calls
    assert path.read_text()==line
    assert 'FAILED_INFRASTRUCTURE' in (tmp_path/'reports/latest.md').read_text()


def test_duplicate_legacy_runs_not_double_billed(tmp_path,harness):
    r=RunRecord(run_id='legacy',started_at=pipeline.utcnow(),finished_at=pipeline.utcnow(),mode='cycle',cost_usd=.2).model_dump()
    path=tmp_path/'state/runs.jsonl';path.parent.mkdir();path.write_text((json.dumps(r)+'\n')*2)
    rec,ai,store=harness({'discovery':[{'candidates':[]}]})
    assert rec.ok and len(store.legacy_runs)==1
    assert pipeline.daily_cost_so_far()==pytest.approx(.201)


def test_conflicting_legacy_duplicate_is_corruption(tmp_path,harness):
    r=RunRecord(run_id='legacy',started_at=pipeline.utcnow(),finished_at='',mode='cycle',cost_usd=.2).model_dump()
    path=tmp_path/'state/runs.jsonl';path.parent.mkdir();path.write_text(json.dumps(r)+'\n'+json.dumps({**r,'cost_usd':.1})+'\n')
    with pytest.raises(StateError): Store(tmp_path)


def test_daily_limit_stops_before_provider(harness,tmp_path):
    r=RunRecord(run_id='legacy',started_at=pipeline.utcnow(),finished_at=pipeline.utcnow(),mode='cycle',cost_usd=.50)
    Store(tmp_path).checkpoint(r,[])
    rec,ai,_=harness()
    assert rec.ok and rec.outcome=='BUDGET_STOP' and not ai.calls


def test_atomic_write_failure_preserves_previous_bytes(tmp_path,monkeypatch):
    path=tmp_path/'state.jsonl';atomic_write(path,'{"original":true}\n')
    def fail(*args): raise OSError('simulated disk failure')
    monkeypatch.setattr(state.os,'replace',fail)
    with pytest.raises(OSError):atomic_write(path,'{"different":true}\n')
    assert path.read_text()=='{"original":true}\n'
    assert list(tmp_path.iterdir())==[path]


def test_checkpoint_replace_idempotent(tmp_path):
    store=Store(tmp_path)
    r=RunRecord(run_id='same',started_at=pipeline.utcnow(),finished_at='',mode='cycle')
    store.checkpoint(r,[]);store.checkpoint(r,[])
    assert len(Store(tmp_path).runs())==1


def test_process_death_reservation_blocks_restart(harness,tmp_path,monkeypatch):
    # SystemExit bypasses Exception handlers, like a killed worker after dispatch.
    with pytest.raises(SystemExit):harness({'discovery':[SystemExit()]})
    pending=Store(tmp_path).runs()[-1]
    assert pending['pending_stage']=='discovery' and pending['reserved_usd']==.035
    rec,ai,_=harness()
    assert rec.outcome=='BUDGET_STOP' and not ai.calls


def test_durable_call_cost_survives_later_candidate_failure(harness,tmp_path):
    rec,ai,store=harness({'discovery':[{'candidates':[candidate(0),{},candidate(1)]}]})
    assert rec.survivors==2 and rec.normalization_rejected==1
    assert rec.cost_usd==.005
    rows=state.read_jsonl(tmp_path/'state/transactions.jsonl')
    assert len(rows)==1 and rows[0]['run']['cost_usd']==.005 and len(rows[0]['opportunities'])==2
    assert all(op['status']=='survived' for op in rows[0]['opportunities'])


def test_dedupe_restart_does_not_duplicate_records(harness):
    one,ai,store=harness()
    two,ai,store=harness()
    assert one.survivors==1 and two.duplicates_skipped==1 and len(ai.calls)==1
    assert len(store.opportunities())==1


def test_material_update_moves_state_without_historical_survivor_leak(harness,tmp_path):
    one,ai,store=harness()
    raw=candidate(material_update=True,update_summary='New verified regulatory condition blocks the former pathway')
    raw['evidence'].append({'title':'New filing','url':'https://primary.example/new','source_type':'primary','claim':'new condition'})
    two,ai,store=harness({'discovery':[{'candidates':[raw]}], 'critic':[{**CRITIC,'fatal':True}]},sources=SOURCES|{'https://primary.example/new'})
    assert two.rejected==1 and len(store.opportunities())==1
    assert store.opportunities()[0].status=='rejected'
    assert 'No survivors.' in (tmp_path/'reports/latest.md').read_text()


def test_fake_update_cannot_reopen_rejection(harness):
    rec,_,store=harness({'critic':[{**CRITIC,'fatal':True}]})
    raw=candidate(material_update=True,update_summary='Pretend a structural condition changed with no new provenance')
    rec,ai,store=harness({'discovery':[{'candidates':[raw]}]})
    assert rec.duplicates_skipped==1 and store.opportunities()[0].status=='rejected'
    assert len(ai.calls)==1


def test_real_update_can_reopen_rejection(harness):
    rec,_,store=harness({'critic':[{**CRITIC,'fatal':True}]})
    raw=candidate(material_update=True,update_summary='New enforceable approval changes previously blocked structural access')
    raw['evidence'].append({'title':'Approval','url':'https://primary.example/new','source_type':'primary','claim':'access approval'})
    rec,ai,store=harness({'discovery':[{'candidates':[raw]}]},sources=SOURCES|{'https://primary.example/new'})
    assert rec.survivors==1 and len(store.opportunities())==1


def test_model_cannot_inject_survivor_state(harness):
    raw=candidate(critic_reviewed=True,judge_reviewed=True,status='survived',judgment_confidence=1)
    rec,ai,store=harness({'discovery':[{'candidates':[raw]}], 'critic':[{}]})
    op=store.opportunities()[0]
    assert op.status=='watch' and not op.critic_reviewed and not op.judge_reviewed
    raw=op.model_dump();raw.update(status='survived')
    with pytest.raises(ValueError): Opportunity.model_validate(raw)


def test_single_writer_lock(harness,tmp_path):
    with exclusive_writer(tmp_path):
        rec,ai,_=harness()
    assert not rec.ok and not ai.calls and 'state_lock_unavailable' in rec.notes


def test_state_rejects_malformed_transaction(tmp_path):
    path=tmp_path/'state/transactions.jsonl';path.parent.mkdir();path.write_text('{"run":{},"opportunities":[]}\n')
    with pytest.raises(StateError): Store(tmp_path)


def test_material_updates_in_same_batch_never_duplicate_state(harness):
    a=candidate()
    b=candidate(material_update=True,update_summary='Another filing supposedly changes the economic conditions')
    b['evidence'].append({'title':'new','url':'https://primary.example/new','source_type':'primary','claim':'change'})
    rec,ai,store=harness({'discovery':[{'candidates':[a,b]}]},sources=SOURCES|{'https://primary.example/new'})
    assert rec.duplicates_skipped==1 and len(store.opportunities())==1 and rec.survivors==1


def test_report_disk_failure_not_recorded_as_success(harness,monkeypatch):
    def fail(*args):raise OSError('disk failure')
    monkeypatch.setattr(pipeline,'write_report',fail)
    rec,ai,store=harness()
    assert not rec.ok and not store.runs()[-1]['ok']
    assert store.runs()[-1]['outcome']=='FAILED_INFRASTRUCTURE'
    assert store.runs()[-1]['cost_usd']==rec.cost_usd


def test_bad_survivor_on_disk_fails_closed(tmp_path):
    op=pipeline.normalize_candidate(candidate(),SOURCES).model_dump();op['status']='survived'
    run=RunRecord(run_id='bad',started_at=pipeline.utcnow(),finished_at='',mode='cycle').model_dump()
    path=tmp_path/'state/transactions.jsonl';path.parent.mkdir();path.write_text(json.dumps({'run':run,'opportunities':[op]})+'\n')
    with pytest.raises(StateError):Store(tmp_path)


def test_schedule_active_and_ci_cannot_invoke_paid_cycle():
    import yaml
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    live=yaml.load((root/'.github/workflows/scout.yml').read_text(),Loader=yaml.BaseLoader)
    ci=yaml.load((root/'.github/workflows/ci.yml').read_text(),Loader=yaml.BaseLoader)
    assert live['on']['schedule'] == [{'cron': '0 */4 * * *'}]
    assert 'redesign/**' in ci['on']['push']['branches']
    assert 'OPENAI_API_KEY' not in json.dumps(ci)
    assert 'scout.cli cycle' not in json.dumps(ci)
    select_mode=next(s for s in live['jobs']['scout']['steps'] if s.get('name')=='Select mode')
    assert select_mode['env']['SCOUT_MODE'] == "${{ inputs.mode || 'cycle' }}"
    names=[s.get('name','') for s in live['jobs']['scout']['steps']]
    assert names.index('Verify preceding run persisted')<names.index('Run Scout')
    assert names.index('Preserve recovery artifact')<names.index('Persist state and reports')
