from __future__ import annotations
import argparse,json
from .pipeline import ROOT,hard_gate_reasons,load_yaml,normalize_candidate,run_cycle,write_report,_available_verticals
from .runtime import AIClient

def validate_config()->list[str]:
    errors=[]; cfg=load_yaml(ROOT/'config'/'scout.yaml'); lenses=load_yaml(ROOT/'config'/'lenses.yaml').get('lenses',[])
    for k in ('discovery','critic','judge'):
        m=cfg.get('models',{}).get(k)
        if not m: errors.append(f'missing model {k}')
        elif m not in cfg.get('pricing',{}).get('models',{}): errors.append(f'missing pricing for {m}')
    if not lenses: errors.append('no discovery lenses')
    if float(cfg.get('budget',{}).get('cycle_usd',0))<=0 or float(cfg.get('budget',{}).get('daily_usd',0))<=0: errors.append('invalid budget')
    if 'general' not in _available_verticals(): errors.append('general vertical missing')
    return errors

def calibrate()->int:
    fixture=json.loads((ROOT/'tests'/'fixtures'/'calibration.json').read_text(encoding='utf-8')); failures=[]
    for case in fixture['cases']:
        op=normalize_candidate(case['candidate']); passed=not hard_gate_reasons(op); bad=passed!=case['expected_hard_gate_pass']
        if case.get('expected_vertical') and op.vertical!=case['expected_vertical']: bad=True
        if bad: failures.append(case['name'])
    print(json.dumps({'cases':len(fixture['cases']),'failures':failures},indent=2)); return 1 if failures else 0

def preflight()->int:
    errors=validate_config()
    if errors: print(json.dumps({'ok':False,'errors':errors},indent=2)); return 2
    cfg=load_yaml(ROOT/'config'/'scout.yaml'); ai=AIClient(cfg['pricing']); ai.validate_models(list(cfg['models'].values())); print(json.dumps({'ok':True,'models':sorted(set(cfg['models'].values()))},indent=2)); return 0

def main()->None:
    p=argparse.ArgumentParser(); p.add_argument('mode',choices=['cycle','report','calibrate','validate','preflight']); args=p.parse_args()
    if args.mode=='cycle':
        rec=run_cycle(); print(rec.model_dump_json(indent=2)); raise SystemExit(0 if rec.ok else 2)
    if args.mode=='report': print(write_report()); return
    if args.mode=='calibrate': raise SystemExit(calibrate())
    if args.mode=='validate':
        errs=validate_config(); print(json.dumps({'ok':not errs,'errors':errs},indent=2)); raise SystemExit(1 if errs else 0)
    raise SystemExit(preflight())
if __name__=='__main__': main()
