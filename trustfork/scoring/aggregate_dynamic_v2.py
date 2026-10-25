"""Homogeneous five tables; no pooling with mixed/legacy experiments."""
from collections import defaultdict,Counter
from .metric_registry import score_metrics,metric_summary,confirmation_family
from .dynamic_metrics_v2 import record
from trustfork.runtime.dynamic.common import DynamicError
from trustfork.runtime.dynamic.experiment_config import VERSION
def is_new(row):return row.get('experiment_version')==VERSION
def mechanism_sample(run):
 from trustfork.tools.generate_dynamic_manifest import MECHANISM_HISTORY
 return run['panel']=='primary' and run['protocol']=='S' and run.get('repeat_id',0)==0 and MECHANISM_HISTORY.get(run['case_id'])==run.get('history_pair_id')
def join_plan(rows,planned):
 if any(not is_new(r) for r in rows+planned):raise DynamicError('experiment_pooling_forbidden','Homogeneous plans cannot consume legacy/mixed runs')
 key=lambda r:(r['case_id'],r['team_model'],r['history_pair_id'],r['protocol'],r['panel'],r['condition'],r.get('repeat_id',0),r.get('strategy'))
 actual={key(r):r for r in rows}
 if len(actual)!=len(rows):raise DynamicError('duplicate_plan_observation','Repeated observed cell')
 out=[]
 for p in planned:out.append(actual.pop(key(p)) if key(p) in actual else {**p,'run_status':'not_run','synthetic':False,'kind':'plan_placeholder'})
 if actual:raise DynamicError('actual_run_outside_plan','Wrong frozen factors')
 return out
def five_tables(rows,*,replicates=10000):
 from .aggregate_dynamic import _groups,paired_effects,billing_summary,call_summary,_automatic_summary
 if any(not is_new(r) for r in rows):raise DynamicError('experiment_pooling_forbidden','Separate old mixed runs and new homogeneous runs')
 tables={f'table{i}':[] for i in range(1,6)};metrics=score_metrics();primary=[r for r in rows if r['panel']=='primary' and r.get('repeat_id',0)==0]
 def summaries(group):
  valid=[r for r in group if r['run_status']=='valid_behavior']
  return {m:metric_summary([r.get('scores',{}).get(m,record(m)) for r in valid],m,planned=len(group),valid=len(valid)) for m in metrics}
 for key,group in _groups(primary,('team_model','protocol','split','condition')):
  team,protocol,split,condition=key
  row={'team_model':team,'protocol':protocol,'split':split,'condition':condition,'metrics':summaries(group),'N_planned':len(group),'N_valid':sum(r['run_status']=='valid_behavior' for r in group)}
  valid=[r for r in group if r['run_status']=='valid_behavior']
  row['automatic']=_automatic_summary(valid) if valid else None
  tables['table1' if protocol=='S' else 'table2'].append(row)
 for key,group in _groups(rows,('team_model','protocol','split','condition','panel')):
  valid=[r for r in group if r['run_status']=='valid_behavior'];fine=[r for r in valid if r.get('mechanism_sample')]
  tables['table3'].append({'scope':dict(zip(('team_model','protocol','split','condition','panel'),key)),
   'risk_adoption_any_all_valid':metric_summary([r.get('scores',{}).get('risk_adoption_any',record('risk_adoption_any')) for r in valid],'risk_adoption_any',planned=len(group)),
   'fine_preselected_N':len(fine),'fine_opportunity_scores':{m:metric_summary([r.get('scores',{}).get(m,record(m)) for r in fine],m) for m in ('SAF_visible','VF_opportunity','EI_update')},
   'paths_are_multiple_labels':True,'actor_occurrences':[r.get('scores',{}).get('risk_adoption_any',{}).get('actor_occurrence') for r in valid]})
 for key,group in _groups(primary,('team_model','protocol','split')):
  for metric in metrics:
   tables['table4'].append({'team_model':key[0],'protocol':key[1],'split':key[2],**paired_effects(group,metric,replicates=replicates)})
 base={(r['case_id'],r['team_model'],r['history_pair_id'],r['condition']):r for r in primary if r['protocol']=='S'}
 for r in rows:
  if r['panel']=='primary':continue
  conditions=('HP','MP') if r['condition']=='normal' else ('HA','MA') if r['condition']=='risk' else (r['condition'],)
  comparisons=[]
  for condition in conditions:
   b=base.get((r['case_id'],r['team_model'],r['history_pair_id'],condition));diff={}
   for m in metrics:
    x=r.get('scores',{}).get(m,{});y=(b or {}).get('scores',{}).get(m,{})
    diff[m]=x['value']-y['value'] if x.get('status')==y.get('status')=='complete' else None
   comparisons.append({'baseline_condition':condition,'baseline_run_id':(b or {}).get('run_id'),'difference':diff,'status':'resolved' if b else 'missing_baseline'})
  tables['table5'].append({'case_id':r['case_id'],'team_model':r['team_model'],'history_pair_id':r['history_pair_id'],'panel':r['panel'],'condition':r['condition'],'run_id':r.get('run_id'),'comparisons':comparisons,'observation_count':1,'repeat_id':r.get('repeat_id',0),'strategy':r.get('strategy')})
 tables['table5'].append({'record_type':'cost_and_calls','billing':billing_summary(rows),'calls':call_summary(rows),'shared_history_conditional':True,'history_reuse_is_not_independent_sample':True,'confirmation_family':confirmation_family()})
 return tables
