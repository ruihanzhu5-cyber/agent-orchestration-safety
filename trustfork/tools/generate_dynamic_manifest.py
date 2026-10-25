"""Enumerate homogeneous plan; references are not executed artifacts."""
import argparse,json,hashlib
from pathlib import Path
from collections import Counter
from trustfork.runtime.dynamic.common import read_json,config_dir,digest,canonical,write_json
from trustfork.runtime.dynamic.case_loader import HISTORY_CASES,CONFIRM_CASES
from trustfork.runtime.dynamic.experiment_config import resolve_experiment,block_id,TEAMS,HISTORY_PAIRS,VERSION
CONDITIONS=('HP','HA','MP','MA');FOUR=('p004','p006','p008','p028')
MECHANISM_HISTORY=read_json(config_dir()/'mechanism_history.v1.json')['mapping']
def plan_ref(block,condition):return 'plan_'+digest([block,condition])[:24]
def generate_plan(catalog=None):
 from trustfork.scoring.dynamic_pipeline import scorer_manifest
 from trustfork.runtime.dynamic.goals import bind_goals
 from trustfork.runtime.dynamic.profile_service import build_profile,ProfileService
 catalog=catalog or read_json(config_dir()/'cases.json');t3=sorted(set(catalog)-HISTORY_CASES);rows=[];scorer=scorer_manifest()['manifest_hash'];profiles={}
 def add(cases,histories,protocol,panel='primary',conditions=CONDITIONS,repeats=(0,),strategies=(None,)):
  for case in cases:
   for team in TEAMS:
    for hist in histories or (MECHANISM_HISTORY[case],):
     for repeat in repeats:
      for strategy in strategies:
       cfg=resolve_experiment(case,team_model=team,history_pair_id=hist,protocol=protocol,panel=panel,repeat_id=repeat)
       bid=block_id(case,cfg,strategy);base=block_id(case,resolve_experiment(case,team_model=team,history_pair_id=hist))
       prefix='prefix-plan_'+digest([VERSION,case,team,hist])[:24]
       for condition in conditions:
        norm={'normal':'HP','risk':'HA'}.get(condition,condition)
        level='none' if panel=='no_external_portfolio' else ('80' if norm[0]=='H' else '60') if panel=='80_60' else norm[0]
        key=(cfg.q,level,cfg.profile_corpus_id,cfg.r,panel=='r70',panel=='reminder')
        if key not in profiles:
         bundles={cfg.q:build_profile(cfg.q,level,corpus=cfg.profile_corpus_id),cfg.r:build_profile(cfg.r,'M' if panel=='r70' else 'none',corpus='R'+str(int(cfg.profile_corpus_id[1])%4+1))}
         service=ProfileService('plan',bundles,reminder=panel=='reminder');profiles[key]=digest({a:service.get_public_profile(a,'full') for a in cfg.display_order})
        goals=bind_goals(catalog[case],None,norm,experiment=cfg)
        if strategy:goals['goals'][cfg.q]+='\n'+read_json(config_dir()/'profiles.json')['strategies'][strategy]
        baselines=[plan_ref(base,c) for c in (('HP','MP') if condition=='normal' else ('HA','MA'))] if panel=='no_external_portfolio' else [plan_ref(base,norm)] if panel!='primary' else []
        rows.append({**cfg.export(),'schema_version':'1.0','protocol_version':'dynamic-join-v9-trajectory-portfolio','mode':'plan-only','kind':'formal',
         'case_id':case,'source_task_path':catalog[case]['source_task_path'],'source_asset_hash':catalog[case]['deployed_asset_hash'],
         'split':catalog[case]['split'],'suite':catalog[case]['suite'],'base_task_family':catalog[case]['base_task_family'],
         'plan_run_id':plan_ref(bid,condition),'block_id':bid,'run_id':None,'checkpoint_id':None,'prefix_plan_ref':prefix,
         'late_prefix_plan_ref':'late_'+prefix if protocol=='L' else None,'condition':condition,'goal_condition':norm,'strategy':strategy,
         'main_model':team,'layout':None,'corpus':None if panel=='no_external_portfolio' else cfg.profile_corpus_id,
         'baseline_plan_refs':baselines,'baseline_plan_ref':baselines[0] if len(baselines)==1 else None,'matched_S_plan_ref':plan_ref(base,norm) if protocol=='F' else None,
         'profile_hash':profiles[key],'goal_hash':digest(goals['goals']),'scorer_hash':scorer,
         'mechanism_sample':panel=='primary' and protocol=='S' and MECHANISM_HISTORY.get(case)==hist,
         'run_order':sorted(conditions,key=lambda c:hashlib.sha256((bid+'|'+c).encode()).hexdigest()).index(condition),
         'budget':{'requests':120,'output_tokens':48000,'per_request':4096,'stage_seconds':1200},
         'unresolved':['precise_api_bindings','executed_history','actual_checkpoint_id','judge_context_capacity'],'formal_ready':False})
 add(t3,HISTORY_PAIRS,'S');add(t3,HISTORY_PAIRS,'F');add(sorted(CONFIRM_CASES),HISTORY_PAIRS,'S','80_60')
 add(sorted(CONFIRM_CASES),HISTORY_PAIRS,'S','no_external_portfolio',('normal','risk'))
 for panel in ('r70','self_on_request','reminder'):add(FOUR,None,'S',panel)
 add(FOUR,None,'S','strategy',('HA','MA'),strategies=('context_negotiation','peer_collaboration'))
 add(FOUR,None,'S','repeat',repeats=(1,2));add(FOUR,None,'L','late_join')
 ids={r['plan_run_id'] for r in rows};counts=Counter(r['block_id'] for r in rows)
 assert len(rows)==len(ids)==1248 and len(counts)==336 and Counter(counts.values())=={4:288,2:48}
 assert Counter(r['protocol'] for r in rows)=={'S':800,'F':416,'L':32}
 for r in rows:assert set(r['baseline_plan_refs'])<=ids and (not r['matched_S_plan_ref'] or r['matched_S_plan_ref'] in ids)
 for team in TEAMS:
  sample=[r for r in rows if r['mechanism_sample'] and r['team_model']==team and r['condition']=='HP']
  assert Counter(r['q'] for r in sample)=={'C':9,'D':9} and len(sample)==18
  assert Counter(r['display_order'][0]==r['q'] for r in sample)=={True:9,False:9}
  primary=[r for r in rows if r['protocol']=='S' and r['panel']=='primary' and r['team_model']==team and r['condition']=='HP']
  assert Counter(r['profile_corpus_id'] for r in primary)=={f'R{i}':13 for i in range(1,5)}
 return rows
def auxiliary_plans():
 return {'history_bundles':[{'team_model':t,'history_pair_id':h,'history_task_ids':list(tasks),'history_bundle_id':None,'mode':'plan-only'} for t in TEAMS for h,tasks in HISTORY_PAIRS.items()],
 'smoke':[{**resolve_experiment(c,team_model=t,protocol=p).export(),'case_id':c,'condition':k,'mode':'plan-only','run_id':None,'checkpoint_id':None} for c in ('p001','p024') for t in TEAMS for p in ('S','F') for k in CONDITIONS]}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan-only',action='store_true',required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--legacy',action='store_true');a=p.parse_args()
 if a.legacy:
  from .generate_dynamic_manifest_legacy import generate_plan as legacy,auxiliary_plans as aux
  rows=legacy();extra=aux()
 else:rows=generate_plan();extra=auxiliary_plans()
 if a.out.exists():raise FileExistsError(a.out)
 a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_bytes(b''.join(canonical(r)+b'\n' for r in rows));write_json(a.out.with_suffix('.auxiliary.json'),extra)
 summary={'formal_branches':len(rows),'blocks':len({r['block_id'] for r in rows}),'mechanism_branches':sum(r['mechanism_sample'] for r in rows),'planned_history_bundles':len(extra.get('history_bundles',[])),'planned_history_task_attempts':8 if not a.legacy else 16,'smoke':len(extra['smoke']),'executed':0,'mode':'plan-only','counts_by_panel':dict(Counter(r['panel'] for r in rows)),'formal_ready':False}
 write_json(a.out.with_suffix('.summary.json'),summary);print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
