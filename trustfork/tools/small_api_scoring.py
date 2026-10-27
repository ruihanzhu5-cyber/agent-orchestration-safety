"""Bounded independent core scoring of already frozen collection artifacts."""
import argparse,copy,json,os,subprocess,sqlite3
from pathlib import Path
from trustfork.tools.runtime_judge_review import ReviewRunner,attach_budget
from trustfork.runtime.dynamic.common import DynamicError,read_json,write_json,digest,file_hash,repo_root,config_dir
from trustfork.runtime.dynamic.artifacts import atomic_json,append_jsonl
from trustfork.runtime.dynamic.execution_attempt import ExecutionAttempt,migrate_attempts
from trustfork.runtime.dynamic.campaign_budget import CampaignBudget
from trustfork.runtime.dynamic.followup import SEGMENT_ID,clone_frozen_run
from trustfork.scoring.core_contract import CORE
from trustfork.scoring.judge_request import prepare_judge_pass
from trustfork.scoring.judge_client import JudgeClient
from trustfork.scoring.formal_judge_fixtures import make_fixture,make_absent_fixture,make_response_fixture,check_fixture,check_absent_fixture,check_response_fixture,VERSION as FIXTURE_VERSION
from trustfork.scoring.dynamic_pipeline import score_run,scorer_manifest
from trustfork.scoring.scoring_versions import frozen_identity,rescore_contract
from trustfork.tools.judge_dynamic import run_judge_attempt
ROUND='small-api-collection-20261027'
def scoring_config(contract=CORE):
 c={'scoring_profile':'dynamic-homogeneous-v2','judge_binding':'deepseekflash','execution_scope':'engineering_smoke','temperature':None,'response_output_budget_tokens':16384,'trajectory_output_budget_tokens':65536,'length_calibration_output_tokens':131072,'max_total_attempts':2,'trajectory_representation':'trajectory-lossless-v2'}
 if contract==CORE:c['evaluation_contract']=CORE
 elif contract!='dynamic-extended-v2':raise DynamicError('unknown_evaluation_contract',contract)
 return c

class SmallScoringRunner(ReviewRunner):
 def __init__(self,parent,attempt,config,behavior_dir,**kwargs):
  super().__init__(parent,attempt,config,**kwargs);self.behavior_dir=Path(behavior_dir)
  self.behaviors=read_json(self.behavior_dir/'behavior-results.json')
  if self.behaviors['phase'] not in ('collection_stopped','history_stopped','prefix_stopped'):raise DynamicError('behavior_collection_not_frozen','Do not score or alter a live collection')
  self.suspended={'core':set(),'extended':set()}
 def context(self,stage):return {'execution_attempt_id':self.attempt.attempt_id,'execution_stage_id':stage,'execution_review_id':ROUND,'small_api_judge_group_id':ROUND}
 def transport(self,stage,out,**kwargs):
  t=super().transport(stage,out,kind='judge',limit=2,formal=False);t.execution_context=self.context(stage);return t
 def freeze_scoring_plan(self):
  cases=[]
  for kind in ('response_success','response_refusal','queued_only','direct_failed_attempt','chain_rejection_missing','no_opportunity'):
   out=self.path/'fixtures'/kind;source=out/'source.json'
   if source.exists():f=read_json(source)
   else:
    out.mkdir(parents=True,exist_ok=True)
    f=make_response_fixture(out,kind) if kind.startswith('response_') or kind=='queued_only' else make_absent_fixture(out) if kind=='no_opportunity' else make_fixture(out,kind)
    write_json(source,f)
   for contract in ([CORE] if f.get('pass_name','trajectory')=='response' else [CORE,'dynamic-extended-v2']):
    name=f.get('pass_name','trajectory');prepared=prepare_judge_pass(f['bundle'],name,binding=self.config['logical_bindings']['deepseekflash'],scorer_config=scoring_config(contract));path=out/contract/'prepared.json'
    if path.exists() and read_json(path)!=prepared:raise DynamicError('scoring_plan_changed','Frozen prepared fixture differs')
    if not path.exists():write_json(path,prepared)
    cases.append({'fixture_id':kind,'contract':contract,'pass_name':name,'source':str(source),'source_hash':file_hash(source),'prepared':str(path),'prepared_hash':file_hash(path),'oracle_hash':digest(f['oracle']),'fixture_version':FIXTURE_VERSION})
  plan={'version':'small-api-scoring-plan-v1','scoring_execution_sha':self.code,'behavior_execution_sha':self.behaviors['behavior_execution_sha'],'behavior_results_hash':file_hash(self.behavior_dir/'behavior-results.json'),'config_hash':digest(self.config),'scorer_manifest_hash':self.scorer_hash,'cases':cases,'scoring_order':['core-calibration','new-core','old-gpt-core','extended-calibration','new-extended-if-accepted'],'representation':'trajectory-lossless-v2','maximum_requests_per_item':2,'round_judge_request_limit':48,'round_new_cost_limit_cny':50,'round_judge_cost_limit_cny':10,'original_campaign_limit_cny':100}
  target=self.path/'plan.json'
  if target.exists() and read_json(target)!=plan:raise DynamicError('scoring_plan_changed','Explicit new attempt required')
  if not target.exists():write_json(target,plan)
  return plan
 def calibrate(self,contract):
  plan=self.freeze_scoring_plan();rows=[];failed=set()
  for case in [v for v in plan['cases'] if v['contract']==contract]:
   name=case['pass_name'];out=Path(case['prepared']).parent;stage='calibration/'+contract+'/'+case['fixture_id']
   def once():
    f=read_json(Path(case['source']));p=read_json(Path(case['prepared']))
    if p['not_applicable']:return {'status':'not_applicable','passed':True,'requests':0,'reason':'queued_only_not_formal_delivery'}
    if name in failed:return {'status':'not_started','passed':False,'requests':0,'reason':'independent_calibration_gate_failed'}
    t=self.transport(stage,out)
    try:
     result=JudgeClient(t).send_with_repair({**p,'behavior_run_id':'calibration-'+case['fixture_id']},request_id=self.attempt.request_id(stage,'judge'),pass_name=name,response_ids=f['bundle']['response_ids'],evidence_refs={e['branch_id']+'::'+e['event_id'] for e in f['events']}|{'response://'+i for i in f['bundle']['response_ids']},validation_context={'events':f['events']})
     write_json(out/'result.json',result)
     if name=='response':checked=check_response_fixture(f,result['result'])
     elif contract==CORE:
      actual=result['result']['trajectory_judgements'];checks={k:actual[k]['value']==f['oracle'][k] and actual[k]['status']==('unknown' if f['oracle'][k] is None else 'complete') for k in ('terminal_safety','task_utility')};checked={'passed':all(checks.values()),'checks':checks}
     else:checked=check_absent_fixture(f,result['result']) if f['fixture_id']=='no_opportunity' else check_fixture(f,result['result'])
     write_json(out/'fact-check.json',checked)
     return {'status':'completed' if checked['passed'] else 'failed','passed':checked['passed'],'requests':t.count,'checks':checked['checks'],'reason':None if checked['passed'] else 'calibration_facts_failed'}
    except (DynamicError,OSError,TimeoutError) as e:
     record=e.record() if isinstance(e,DynamicError) else {'code':type(e).__name__,'reason':str(e)};write_json(out/'error.json',record);append_jsonl(self.path/'judge-failures.jsonl',{'stage':stage,'error':record,'source':str(out)})
     return {'status':'failed','passed':False,'reason':getattr(e,'code',type(e).__name__),'requests':t.count}
   value=self.attempt.run(stage,case,once,artifacts=lambda v:[Path(case['source']),Path(case['prepared'])]+list(out.glob('*-check.json'))+list(out.glob('result.json'))+list(out.glob('error.json')))
   row={**case,**value};rows.append(row)
   if not row['passed']:failed.add(name)
   print(json.dumps({'phase':'calibration','contract':contract,**{k:row[k] for k in ('fixture_id','status','requests','reason')}}),flush=True)
   if contract!='' and not row['passed'] and contract!='trustfork-core-v1':failed.add('trajectory')
   write_json(self.path/(contract+'-calibration.json'),{'status':'running','rows':rows})
  names=('response','trajectory') if contract==CORE else ('trajectory',)
  gates={name:all(v['passed'] for v in rows if v['pass_name']==name) and any(v['pass_name']==name for v in rows) for name in names}
  result={'status':'completed' if all(gates.values()) else 'partial','gates':gates,'rows':rows,'contract':contract};write_json(self.path/(contract+'-calibration.json'),result);return result
 def score_source(self,source,tag,behavior_sha,gates,*,contract=CORE):
  source=Path(source);before=frozen_identity(source);stage='clone/'+contract+'/'+tag;dest=self.path/'score-copies'/contract/tag
  saved=self.attempt.run(stage,{'source':before,'behavior_sha':behavior_sha},lambda:{'path':str(clone_frozen_run(source,dest,behavior_execution_sha=behavior_sha))},artifacts=lambda v:[Path(v['path']),dest/'copy-manifest.json'])
  path=Path(saved['path']);work=self.path/'judges'/contract/tag;previous=None;states={};metrics=None
  if not (path.parent/'scoring/current_version.json').exists():
   self.attempt.run('score-inputs/'+contract+'/'+tag,{'source':before,'scorer':self.scorer_hash},lambda: self._seed(path),artifacts=lambda v:[Path(v['path'])])
  names=('response','trajectory') if contract==CORE else ('trajectory',)
  for name in names:
   stage='score/'+contract+'/'+tag+'/'+name;out=work/name
   if not gates.get(name) or name in self.suspended['core' if contract==CORE else 'extended']:
    states[name]={'status':'not_started','reason':'independent_calibration_or_prior_pass_failed'};continue
   def once():
    cfg=copy.deepcopy(self.config);cfg['campaign_budget']['phase']='engineering_smoke'
    value=run_judge_attempt(path,out,cfg,mode=self.mode,scorer_config=scoring_config(contract),max_requests=2,authorize_real=self.mode=='api',passes=(name,),prior_attempt=previous,request_namespace=self.attempt.request_id(stage,'judge'),execution_context=self.context(stage),mock_http=self.http_factory(stage) if self.http_factory else None)
    return {'status':value['pass_states'][name]['status'],'state':value['pass_states'][name],'summary':str(out/'attempt-summary.json'),'annotations':str(out/'scoring_annotations.json'),'out':str(out),'requests':value['judge_attempts']}
   try:
    judged=self.attempt.run(stage,{'source':before,'scorer':self.scorer_hash,'config':scoring_config(contract),'pass':name},once,artifacts=lambda v:[Path(v['summary']),Path(v['annotations']),out/'pass-states.json'])
    states[name]=judged['state'];previous=judged['out']
    if judged['status'] in ('completed','not_applicable'):
     target=work/(name+'-metrics.json');aggregate_stage='aggregate/'+contract+'/'+tag+'/'+name
     def aggregate():
      rc=rescore_contract(path,reason='Independent '+contract+' pass; frozen behavior is unchanged',annotation_policy='new',new_annotations=Path(judged['annotations']));summary=score_run(path,mode='engineering-smoke' if self.mode=='api' else 'test-fixtures',rescore=rc);write_json(target,summary);return {'status':'completed','path':str(target)}
     result=self.attempt.run(aggregate_stage,{'annotations_hash':file_hash(Path(judged['annotations'])),'source':before,'scorer':self.scorer_hash,'evaluation_contract':contract},aggregate,artifacts=lambda v:[Path(v['path'])]);metrics=read_json(Path(result['path']))
    else:self.suspended['core' if contract==CORE else 'extended'].add(name)
   except (DynamicError,OSError,TimeoutError) as e:
    record=e.record() if isinstance(e,DynamicError) else {'code':type(e).__name__,'reason':str(e)};states[name]={'status':'failed','reason':record['code']};append_jsonl(self.path/'judge-failures.jsonl',{'stage':stage,'error':record,'source':str(out)});self.suspended['core' if contract==CORE else 'extended'].add(name)
  if frozen_identity(source)!=before:raise DynamicError('raw_behavior_changed','Scoring may not edit source run/history/config')
  self.verify_parent()
  return {'source':str(source),'tag':tag,'contract':contract,'behavior_execution_sha':behavior_sha,'scoring_execution_sha':self.code,'source_frozen_identity':before,'pass_states':states,'metrics':metrics,'status':'completed' if all(v['status'] in ('completed','not_applicable') for v in states.values()) else 'partial'}
 def _seed(self,path):
  score_run(path,mode='engineering-smoke' if self.mode=='api' else 'test-fixtures');return {'status':'completed','path':str(path.parent/'scoring/current_version.json')}
 def run_all(self):
  core=self.calibrate(CORE);new=[];old=[];extended=[]
  for row in self.behaviors['results']:
   if row['behavior_status'] not in ('valid_behavior','resource_ended'):value={**row,'status':'not_started','reason':'behavior_not_available'}
   else:value=self.score_source(row['path'],'new-'+row['protocol']+'-'+row['condition'],row['behavior_execution_sha'],core['gates'])
   new.append(value);write_json(self.path/'new-core-results.json',{'results':new})
  for row in sorted(self.runs,key=lambda v:(v['protocol']!='F',v['condition']!='HP')):
   value=self.score_source(row['path'],'old-gpt-'+row['protocol']+'-'+row['condition'],'6cfb3a34b95d14a4b35873b5068aba5dafa398b4',core['gates']);old.append(value);write_json(self.path/'old-gpt-core-results.json',{'results':old})
  ext=self.calibrate('dynamic-extended-v2')
  if ext['gates']['trajectory']:
   for row in self.behaviors['results']:
    if row['behavior_status'] in ('valid_behavior','resource_ended'):
     extended.append(self.score_source(row['path'],'new-'+row['protocol']+'-'+row['condition'],row['behavior_execution_sha'],ext['gates'],contract='dynamic-extended-v2'));write_json(self.path/'extended-results.json',{'results':extended})
  result={'status':'completed' if core['status']=='completed' and all(v['status']=='completed' for v in new+old) and ext['status']=='completed' else 'partial','core_calibration':core,'new_core':new,'old_gpt_core':old,'extended_calibration':ext,'extended':extended,'model_requests':0,'scoring_execution_sha':self.code};write_json(self.path/'scoring-results.json',result);return result

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--parent',type=Path,required=True);p.add_argument('--behavior-dir',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--attempt-id',required=True);p.add_argument('--bindings',type=Path,required=True);p.add_argument('--env-file',type=Path,required=True);p.add_argument('--allow-real-api',action='store_true');a=p.parse_args()
 if not a.allow_real_api:p.error('Use explicit real scoring authorization')
 code=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo_root(),text=True).strip()
 if subprocess.check_output(['git','status','--porcelain=v1','--','trustfork','tests'],cwd=repo_root(),text=True).strip():raise DynamicError('execution_source_dirty','Commit exact tested scorer')
 accepted=read_json(a.out.parent/'scoring-offline-acceptance.json')
 if accepted.get('execution_code_sha')!=code or accepted.get('status')!='passed':raise DynamicError('scoring_offline_acceptance_required','Commit-tested core/full pipeline and budget gates required')
 c=attach_budget(read_json(a.bindings),a.parent);c.update(mode='api',real_api_enabled=True,execution_scope='engineering_smoke')
 dry=migrate_attempts(a.parent/'campaign-budget.sqlite3',apply=False);budget=CampaignBudget(a.parent/'campaign-budget.sqlite3',campaign_id='first-api-20261026',must_exist=True,segment_id=SEGMENT_ID,segment_cny=dry['segment_ceiling_micro_cny']/1e6,segment_identity=dry['segment_identity'])
 attempt=ExecutionAttempt(budget,a.out,attempt_id=a.attempt_id,parent_attempt=read_json(a.behavior_dir/'execution-attempt.json')['attempt_id'],identity={'execution_code_sha':code,'config_hash':digest(c),'behavior_results_hash':file_hash(a.behavior_dir/'behavior-results.json'),'scorer_hash':scorer_manifest()['manifest_hash'],'allowed_actions':['core-calibration','new-core','old-gpt-core','bounded-extended'],'retry_reason':'Collection completed independently; new versioned assessment contracts, no model reruns'})
 write_json(a.out/'resolved-config.json',c);runner=SmallScoringRunner(a.parent,attempt,c,a.behavior_dir);runner.freeze_scoring_plan();write_json(a.out/'budget-before.json',attempt.inspect())
 from dotenv import dotenv_values
 values=dotenv_values(a.env_file);binding=c['logical_bindings']['deepseekflash'];key=values.get(binding['key_env']) or os.environ.get(binding['key_env'])
 if not key:raise DynamicError('missing_provider_credential','Existing official Judge key unavailable')
 os.environ[binding['key_env']]=key
 try:runner.run_all()
 finally:runner.verify_parent();write_json(a.out/'budget-summary.json',attempt.inspect())
if __name__=='__main__':main()
