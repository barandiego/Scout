from __future__ import annotations
import argparse,json
from .pipeline import ROOT,hard_gate_reasons,load_yaml,normalize_candidate,run_cycle,write_report,_available_verticals
from .runtime import AIClient

def validate_config()->list[str]:
    from . import pipeline
    import math
    errors=[]
    try:
        cfg=load_yaml(pipeline.ROOT/'config'/'scout.yaml')
        lenses=load_yaml(pipeline.ROOT/'config'/'lenses.yaml')['lenses']
        if not isinstance(lenses,list) or not lenses or any(not isinstance(x,dict) or not isinstance(x.get('id'),str) for x in lenses):
            errors.append('invalid_lenses')
        for stage in ('discovery','critic','judge'):
            model=cfg['models'][stage]
            rate=cfg['pricing']['models'][model]
            for key in ('input_per_million','cached_input_per_million','output_per_million'):
                if type(rate[key]) not in (int,float) or not math.isfinite(rate[key]) or rate[key]<0:
                    errors.append('invalid_pricing')
        for key in ('cycle_usd','daily_usd','reserve_discovery_usd','reserve_critic_usd','reserve_judge_usd'):
            value=cfg['budget'][key]
            if type(value) not in (int,float) or not math.isfinite(value) or value<=0:
                errors.append('invalid_budget')
        for key in ('lenses_per_cycle','max_normalized_candidates','max_candidates_to_critic','max_candidates_to_judge',
                    'discovery_max_output_tokens','critic_max_output_tokens','judge_max_output_tokens',
                    'discovery_max_tool_calls','critic_max_tool_calls'):
            value=cfg['limits'][key]
            if type(value) is not int or not 0<value<=10000:
                errors.append('invalid_limit')
        if cfg['limits']['max_normalized_candidates']>100:
            errors.append('candidate_limit_exceeds_boundary')
        if not 0<cfg['limits']['dedupe_similarity']<=1:
            errors.append('invalid_dedupe')
        search=cfg['pricing']['web_search_per_call']
        if type(search) not in (int,float) or not math.isfinite(search) or search<0:
            errors.append('invalid_search_pricing')
        from .trial import read_trial, validate_trial
        errors.extend(validate_trial(read_trial(pipeline.ROOT)))
        if 'general' not in pipeline._available_verticals():
            errors.append('missing_general_vertical')
        for name in pipeline._available_verticals():
            v=load_yaml(pipeline.ROOT/'config'/'verticals'/f'{name}.yaml')
            if not v.get('criteria') or not v.get('fatal_conditions'):
                errors.append('invalid_vertical')
    except (KeyError,TypeError,ValueError,OSError):
        errors.append('invalid_config_structure')
    return sorted(set(errors))

def calibrate()->int:
    fixture=json.loads((ROOT/'tests'/'fixtures'/'calibration.json').read_text(encoding='utf-8')); failures=[]
    for case in fixture['cases']:
        op=normalize_candidate(case['candidate'], {e['url'] for e in case['candidate'].get('evidence',[])}); passed=not hard_gate_reasons(op); bad=passed!=case['expected_hard_gate_pass']
        if case.get('expected_vertical') and op.vertical!=case['expected_vertical']: bad=True
        if bad: failures.append(case['name'])
    print(json.dumps({'cases':len(fixture['cases']),'failures':failures},indent=2)); return 1 if failures else 0

def preflight(*, trial: bool = False)->int:
    errors=validate_config()
    if errors: print(json.dumps({'ok':False,'errors':errors},indent=2)); return 2
    cfg=load_yaml(ROOT/'config'/'scout.yaml')
    from .trial import auto_trial_active
    if not trial and auto_trial_active(ROOT):
        trial=True
    if trial:
        from .trial import read_trial, effective_config, TrialError
        from datetime import datetime, timezone
        try:
            cfg=effective_config(cfg,read_trial(ROOT),datetime.now(timezone.utc))
        except TrialError as exc:
            print(json.dumps({'ok':False,'error':str(exc)},indent=2));return 2
    ai=AIClient(cfg['pricing'])
    ai.validate_models(list(cfg['models'].values()))
    print(json.dumps({'ok':True,'trial':trial,'models':sorted(set(cfg['models'].values()))},indent=2))
    return 0

def main()->None:
    p=argparse.ArgumentParser(); p.add_argument('mode',choices=['cycle','report','calibrate','validate','preflight','library','focus','radar','innovation','trial-cycle','trial-preflight','trial-status','trial-model-check']); args=p.parse_args()
    if args.mode in ('cycle','trial-cycle'):
        from .trial import auto_trial_active
        trial = args.mode=='trial-cycle' or auto_trial_active(ROOT)
        rec=run_cycle(trial=trial)
        print(rec.model_dump_json(indent=2)); raise SystemExit(0 if rec.ok else 2)
    if args.mode=='trial-status':
        from .trial import trial_status
        print(json.dumps(trial_status(ROOT),indent=2)); return
    if args.mode=='trial-model-check':
        from .trial import read_trial, validate_trial
        t=read_trial(ROOT)
        errors=validate_config()+validate_trial(t)
        if errors:
            print(json.dumps({'ok':False,'errors':sorted(set(errors))},indent=2))
            raise SystemExit(2)
        active_models=sorted({t['roles'][s]['model'] for s in ('discovery','critic','judge')})
        client=AIClient(t['pricing'])
        client.validate_models(active_models)
        print(json.dumps({'ok':True,'model_list_checked':active_models,
                          'trial_enabled':False,
                          'inference_calls':0},indent=2))
        return
    if args.mode=='trial-preflight':
        raise SystemExit(preflight(trial=True))
    if args.mode=='report': print(write_report()); return
    if args.mode=='library':
        from .library import write_library
        from .innovation import write_innovation_backlog
        output=write_library(ROOT)
        output['innovation']=write_innovation_backlog(ROOT)
        # Keep all derived research views synchronized with the exact
        # persisted library rather than leaving commercial evidence stale.
        from .commercial import write_commercial_queue
        library=json.loads((ROOT/'reports'/'library.json').read_text(encoding='utf-8'))
        output['commercial_queue']=write_commercial_queue(ROOT,library)
        # A read-only, derived view: never change persistence, dedupe or gates.
        from .focus import write_focus
        output['focus']=write_focus(ROOT,library)
        print(json.dumps(output, indent=2)); return
    if args.mode=='focus':
        from .focus import write_focus
        print(json.dumps(write_focus(ROOT), indent=2)); return
    if args.mode=='innovation':
        from .innovation import write_innovation_backlog
        print(json.dumps(write_innovation_backlog(ROOT), indent=2)); return
    if args.mode=='radar':
        from .radar import run_radar
        print(json.dumps(run_radar(ROOT), indent=2)); return
    if args.mode=='calibrate': raise SystemExit(calibrate())
    if args.mode=='validate':
        errs=validate_config(); print(json.dumps({'ok':not errs,'errors':errs},indent=2)); raise SystemExit(1 if errs else 0)
    raise SystemExit(preflight())
if __name__=='__main__': main()

