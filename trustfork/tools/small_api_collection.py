"""Fixed collection-first pilot. Behavior stages never invoke a Judge or scorer."""
import argparse,copy,json,os,sqlite3,subprocess
from pathlib import Path
from trustfork.tools.runtime_judge_review import ReviewRunner,attach_budget
from trustfork.runtime.dynamic.common import read_json,write_json,digest,file_hash,repo_root,DynamicError
from trustfork.runtime.dynamic.execution_attempt import ExecutionAttempt,migrate_attempts
from trustfork.runtime.dynamic.campaign_budget import CampaignBudget
from trustfork.runtime.dynamic.followup import SEGMENT_ID
from trustfork.runtime.dynamic.artifacts import atomic_json
ROUND_ID='small-api-collection-20261027'
BASELINE='a4182652b778b0e72f95006e0c0e3b7383d3e24c'
PLAN_VERSION='small-api-collection-plan-v1'
def fixed_matrix():
 return [{'case_id':'p001','team_model':'deepseekflash','protocol':p,'condition':c,'repeat_id':0} for p in ('S','F') for c in ('HP','HA')]


def verified_h2_serialization_retry(budget,parent_attempt):
 """One explicit engineering retry; never reuse or improve a research outcome."""
 with budget.tx() as db:
  parent=db.execute('SELECT * FROM execution_attempts WHERE attempt_id=?',(parent_attempt,)).fetchone()
  stage=db.execute('SELECT * FROM execution_stages WHERE attempt_id=? AND stage_id=?',(parent_attempt,'history/H2')).fetchone()
  if not parent or not stage or stage['state']!='failed' or not stage['result']:raise DynamicError('history_retry_not_verified','Only a fully recorded failed H2 planning stage may continue')
  identity=json.loads(parent['identity'])
  if identity.get('history_serialization_retry'):raise DynamicError('history_retry_limit','No recursive preparation retries')
  result=json.loads(stage['result']);path=Path(result['path'])
  for file,hashed in json.loads(stage['artifacts']).items():
   if file_hash(Path(file))!=hashed:raise DynamicError('history_retry_source_changed','Retained failed artifacts changed')
  task=read_json(path);record=task['record']
  if result['status']!='failed_history_retained' or record['task_id']!='p007' or record['termination_reason']!='invalid_fields':raise DynamicError('history_retry_not_verified','Retry is only for the observed extra root-field serialization failure')
  rows=[v for v in db.execute('SELECT * FROM requests') if json.loads(v['metadata']).get('execution_attempt_id')==parent_attempt and json.loads(v['metadata']).get('execution_stage_id')=='history/H2']
  if not rows or any(v['status']!='settled' for v in rows):raise DynamicError('history_retry_unknown_requests','Reconcile every original H2 request before a new preparation attempt')
  retry={'stage':'history/H2','source_attempt':parent_attempt,'source_hash':file_hash(path),'reason':'invalid_fields; explicit field-only format repair; retained failure, no task-outcome selection'}
  for child in db.execute('SELECT attempt_id,identity FROM execution_attempts'):
   if (json.loads(child['identity']).get('history_serialization_retry') or {}).get('source_attempt')!=parent_attempt:continue
   prior=list(db.execute('SELECT * FROM execution_stages WHERE attempt_id=?',(child['attempt_id'],)))
   submitted=any(v['submitted_at'] is not None and json.loads(v['metadata']).get('execution_attempt_id')==child['attempt_id'] for v in db.execute('SELECT * FROM requests'))
   # A source-hash rejection before any network submission did not consume an H2 retry.
   safe=False
   if not submitted and len(prior)==1 and prior[0]['stage_id']=='history/H1' and prior[0]['state']=='failed' and prior[0]['result']:
    value=json.loads(prior[0]['result']);artifacts=json.loads(prior[0]['artifacts'])
    safe=bool(artifacts) and all(Path(k).is_file() and file_hash(Path(k))==v for k,v in artifacts.items()) and read_json(Path(value['path']))['record']['termination_reason']=='fixed_generation_already_started'
   if not safe:raise DynamicError('history_retry_limit','The one engineering H2 continuation already exists')
  return retry

class CollectionRunner(ReviewRunner):
 def apply_t3_budget(self,runtime):
  override=self.attempt.identity.get('t3_budget_override')
  if override:
   from dataclasses import replace
   from trustfork.runtime.dynamic.experiment_config import resolve_runtime_budget
   runtime.runtime_budget=resolve_runtime_budget(runtime.main_model,{**runtime.runtime_budget,**override})
   runtime.experiment=replace(runtime.experiment,runtime_budget=runtime.runtime_budget)
 def transport(self,stage,out,*,kind='model',limit=120,formal=False):
  override=self.attempt.identity.get('t3_budget_override')
  if kind=='model' and override and stage.startswith(('prefix/','t3/')):limit=max(limit,override['request_limit'])
  t=super().transport(stage,out,kind=kind,limit=limit,formal=False)
  retry=self.attempt.identity.get('history_serialization_retry')
  t.execution_context['execution_review_id']=ROUND_ID+('/serialization-repair/'+retry['source_attempt'] if retry and stage=='history' else '')
  if kind=='model':
   repair=self.attempt.identity.get('provider_replay_continuation')
   t.execution_context['model_generation_group_id']=ROUND_ID+('/provider-replay-fix/'+repair['source_attempt'] if repair and stage=='t3/S/HP' else '')+'/'+stage
  return t
 def freeze_collection_plan(self):
  from trustfork.runtime.dynamic.case_loader import load_case
  plan={'version':PLAN_VERSION,'round_id':ROUND_ID,'behavior_execution_sha':self.code,'config_hash':digest(self.config),'matrix':fixed_matrix(),'history_tasks':['p002','p007'],'collection_order':['S/HP','S/HA','F/HP','F/HA'],'source_asset_hashes':{c:load_case(c)['deployed_asset_hash'] for c in ('p001','p002','p007')},'collection_depends_on_judge':False,'original_campaign_cny':100,'original_segment_cny':20,'authorized_segment_cny':self.config['campaign_budget']['segment_cny'],'round_new_cost_ceiling_cny':50,'new_judge_cost_ceiling_cny':10,'new_judge_request_limit':48,'per_scoring_item_max_requests':2,'planned_core_contract':'trustfork-core-v1','planned_extended_representation':'trajectory-lossless-v2','team_runtime_budgets':self.config.get('runtime_budgets'),'t3_budget_override':self.attempt.identity.get('t3_budget_override'),'retained_deadline_history':self.attempt.identity.get('history_deadline_continuation'),'provider_replay_continuation':self.attempt.identity.get('provider_replay_continuation'),'model_transport_request_limit':(self.attempt.identity.get('t3_budget_override') or {}).get('request_limit',120),'source_parent_seal':digest(self.seal)}
  p=self.path/'plan.json'
  if p.exists() and read_json(p)!=plan:raise DynamicError('collection_plan_changed','Frozen matrix/config/code cannot change')
  if not p.exists():atomic_json(p,plan)
  return plan
 def collect(self,*,runtime_factory=None,source_factory=None,history_candidates=()):
  from trustfork.agents.pi_dynamic import PiDynamic,ProviderSource
  from trustfork.runtime.dynamic.prepared_artifacts import prepare_history,load_history,save_prefix,load_prefix,history_contract
  runtime_factory=runtime_factory or PiDynamic;source_factory=source_factory or ProviderSource
  rows=[{**v,'behavior_status':'not_started','core_scoring_status':'not_started','extended_scoring_status':'not_started','overall_status':'partial','behavior_execution_sha':self.code,'scoring_execution_sha':None,'reason':'awaiting_collection'} for v in fixed_matrix()]
  def save(phase):
   value={'phase':phase,'status':'completed' if all(v['behavior_status'] in ('valid_behavior','resource_ended') for v in rows) else 'partial','results':rows,'behavior_execution_sha':self.code,'collection_independent_of_judge':True}
   atomic_json(self.path/'behavior-results.json',value);return value
  save('history');root=self.path/'deepseek';hout=root/'history';t=self.transport('history',hout,limit=240)
  runtime=runtime_factory('p001',hout,provider=t,team_model='deepseekflash');runtime.execution_attempt=self.attempt
  hpath=hout/'history-bundle.json';checks=[]
  if not hpath.exists():
   for candidate in history_candidates:
    candidate=Path(candidate)
    if not candidate.is_file():checks.append({'path':str(candidate),'status':'absent'});continue
    old=read_json(candidate);compatible=old.get('contract')==history_contract(runtime) and old.get('synthetic')==runtime.synthetic
    checks.append({'path':str(candidate),'status':'compatible' if compatible else 'incompatible','source_hash':file_hash(candidate),'contract_hash':digest(old.get('contract')),'required_contract_hash':digest(history_contract(runtime))})
    if compatible:
     load_history(runtime,candidate);hpath=candidate;break
  write_json(root/'history-compatibility.json',{'candidates':checks,'selection_rule':'first completely compatible retained source in frozen candidate order; no outcome selection','old_sources_retained':True})
  try:
   if hpath.exists():bundle=read_json(hpath);load_history(runtime,hpath)
   else:bundle=prepare_history(runtime,source_factory(),hpath)
  except (DynamicError,OSError,TimeoutError) as e:
   for row in rows:row.update(reason=getattr(e,'code',type(e).__name__),failure_phase='history')
   write_json(root/'history-error.json',e.record() if isinstance(e,DynamicError) else {'code':type(e).__name__,'reason':str(e)})
   return save('history_stopped')
  shared_stop=None
  for protocol in ('S','F'):
   if shared_stop:break
   out=root/'blocks'/protocol;stage='prefix/'+protocol;t=self.transport(stage,out)
   runtime=runtime_factory('p001',out,provider=t,team_model='deepseekflash',protocol=protocol);runtime.execution_attempt=self.attempt
   history=load_history(runtime,hpath);self.apply_t3_budget(runtime);prefix_file=out/'prepared-prefix.json'
   def prefix_once():
    prefix=runtime.run_prefix(source_factory(),history=history)
    if prefix['status']!='triggered':
     write_json(out/'preparation-outcome.json',prefix);return {'status':prefix['status'],'path':str(out/'preparation-outcome.json')}
    save_prefix(runtime,prefix,prefix_file);return {'status':'completed','path':str(prefix_file),'checkpoint_id':prefix['checkpoint']['checkpoint_id']}
   try:
    prefix_stage_identity={'history_bundle_id':bundle['bundle_id'],'prefix_identity':runtime.prefix_identity()}
    self.attempt.reuse_parent_stage(stage,prefix_stage_identity)
    saved=self.attempt.run(stage,prefix_stage_identity,prefix_once,artifacts=lambda v:[Path(v['path'])])
   except (DynamicError,OSError,TimeoutError) as e:
    shared_stop=getattr(e,'code',type(e).__name__)
    for row in rows:
     if row['behavior_status']=='not_started':row.update(reason=shared_stop,failure_phase='prefix')
    save('prefix_stopped');break
   if saved['status']!='completed':
    for row in rows:
     if row['protocol']==protocol:row.update(reason='prefix_'+saved['status'])
    save('prefix_not_triggered');continue
   prefix=load_prefix(runtime,Path(saved['path']))
   for condition in ('HP','HA'):
    row=next(v for v in rows if v['protocol']==protocol and v['condition']==condition);stage='t3/'+protocol+'/'+condition
    t=self.transport(stage,out/condition);runtime.provider=t
    def branch_once():
     run=runtime.run_branch(prefix['checkpoint'],condition,source_factory(),attempt=0);path=runtime.directory/'run.json'
     if run['run_status'] not in ('valid_behavior','resource_ended'):
      raise DynamicError('behavior_infrastructure_failure','Runtime did not produce a complete frozen branch',evidence={'run_status':run['run_status'],'path':str(path)})
     frozen=read_json(path)
     if frozen['run_manifest_hash']!=digest(read_json(path.parent/frozen['run_manifest_path'])):raise DynamicError('run_manifest_hash_mismatch','Freeze must finish before behavior stage registration')
     return {'status':run['run_status'],'run_id':run['run_id'],'path':str(path),'termination_reason':run.get('termination_reason'),'source_manifest_hash':run['run_manifest_hash'],'checkpoint_id':prefix['checkpoint']['checkpoint_id'],'new_provider_requests':t.count}
    try:
     saved=self.attempt.run(stage,{'checkpoint':prefix['checkpoint']['checkpoint_id'],'condition':condition,'protocol_identity':runtime.prefix_identity()},branch_once,artifacts=lambda v:[Path(v['path']),Path(v['path']).parent/'run_manifest.json',Path(v['path']).parent/'events.jsonl',Path(v['path']).parent/'prefix-events.json'])
     admitted=[]
     with (Path(saved['path']).parent/'events.jsonl').open() as stream:
      for line in stream:
       event=json.loads(line)
       if event['event_type']=='members_admitted':admitted+=event['payload']['actor_ids']
     row.update({k:v for k,v in saved.items() if k!='status'},behavior_status=saved['status'],admitted_new_members=sorted(set(admitted)&{'C','D'}),reason=None)
    except (DynamicError,OSError,TimeoutError) as e:
     shared_stop=getattr(e,'code',type(e).__name__);row.update(behavior_status='blocked',reason=shared_stop,failure_phase='branch')
     write_json(out/condition/'collection-error.json',e.record() if isinstance(e,DynamicError) else {'code':type(e).__name__,'reason':str(e)})
    save('collection');print(json.dumps({'phase':'behavior',**{k:row.get(k) for k in ('protocol','condition','behavior_status','reason','new_provider_requests','admitted_new_members')}}),flush=True)
    if shared_stop:break
  if shared_stop:
   for row in rows:
    if row['behavior_status']=='not_started':row.update(reason='shared_execution_stop:'+shared_stop)
  self.verify_parent();return save('collection_stopped')

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('operation',choices=('collect',));p.add_argument('--parent',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--attempt-id',required=True);p.add_argument('--bindings',type=Path,required=True);p.add_argument('--env-file',type=Path,required=True);p.add_argument('--allow-real-api',action='store_true');p.add_argument('--retry-h2-from-attempt');p.add_argument('--continue-deadline-history-from-attempt');p.add_argument('--extended-t3-budget',action='store_true');p.add_argument('--continue-provider-replay-from-attempt');a=p.parse_args()
 if not a.allow_real_api:p.error('This collection mode requires the explicit authorized API flag')
 code=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo_root(),text=True).strip()
 if subprocess.run(['git','merge-base','--is-ancestor',BASELINE,code],cwd=repo_root()).returncode:raise DynamicError('collection_baseline_mismatch','Use the designated baseline successor')
 if subprocess.check_output(['git','status','--porcelain=v1','--','trustfork','tests'],cwd=repo_root(),text=True).strip():raise DynamicError('execution_source_dirty','Commit before collection')
 acceptance=read_json(a.out.parent/'collection-offline-acceptance.json')
 if acceptance.get('status')!='passed' or acceptance.get('execution_code_sha')!=code:raise DynamicError('collection_offline_acceptance_required','Exact frozen collection code must pass unit and Docker/Pi integration')
 c=attach_budget(read_json(a.bindings),a.parent);c.update(mode='api',real_api_enabled=True,execution_scope='engineering_smoke')
 if c['judge_binding']!='deepseekflash':raise DynamicError('collection_binding_mismatch','Use the retained official DeepSeek Judge configuration')
 dry=migrate_attempts(a.parent/'campaign-budget.sqlite3',apply=False)
 if dry['needs_migration']:raise DynamicError('execution_migration_required','Original association tables must already exist')
 budget=CampaignBudget(a.parent/'campaign-budget.sqlite3',campaign_id='first-api-20261026',must_exist=True,segment_id=SEGMENT_ID,segment_cny=dry['segment_ceiling_micro_cny']/1e6,segment_identity=dry['segment_identity'])
 from trustfork.runtime.dynamic.retained_history_deadline import inspect_retained_deadline,register_deadline_carry
 from trustfork.runtime.dynamic.provider_replay_continuation import verified_replay_parent
 replay=verified_replay_parent(budget,a.continue_provider_replay_from_attempt) if a.continue_provider_replay_from_attempt else None
 if replay and not a.extended_t3_budget:raise DynamicError('replay_budget_mismatch','Preserve the frozen uniform T3 budget of the saved prefix')
 if sum(bool(v) for v in (a.retry_h2_from_attempt,a.continue_deadline_history_from_attempt,a.continue_provider_replay_from_attempt))>1:raise DynamicError('history_continuation_ambiguous','Choose only one explicit retained source')
 retained=inspect_retained_deadline(budget,c,a.continue_deadline_history_from_attempt) if a.continue_deadline_history_from_attempt else None
 retry=verified_h2_serialization_retry(budget,a.retry_h2_from_attempt) if a.retry_h2_from_attempt else None
 attempt=ExecutionAttempt(budget,a.out,attempt_id=a.attempt_id,parent_attempt=a.continue_provider_replay_from_attempt or a.continue_deadline_history_from_attempt or a.retry_h2_from_attempt or 'runtime-review-20261027-a1',identity={'execution_code_sha':code,'config_hash':digest(c),'allowed_actions':['fixed-behavior-collection-only'],'history_serialization_retry':retry,'history_deadline_continuation':retained['proof'] if retained else None,'provider_replay_continuation':replay,'t3_budget_override':{'request_limit':240,'token_limit':384000,'stage_seconds':3600} if a.extended_t3_budget else None,'retry_reason':'Explicit authorized collection-first plan; never gated by Judge results'})
 if retained:register_deadline_carry(attempt,retained)
 write_json(a.out/'resolved-config.json',c);runner=CollectionRunner(a.parent,attempt,c);runner.freeze_collection_plan();write_json(a.out/'budget-before.json',attempt.inspect())
 from dotenv import dotenv_values
 values=dotenv_values(a.env_file);binding=c['logical_bindings']['deepseekflash'];key=values.get(binding['key_env']) or os.environ.get(binding['key_env'])
 if not key:raise DynamicError('missing_provider_credential','Existing official DeepSeek key unavailable')
 os.environ[binding['key_env']]=key
 try:
  runner.collect(history_candidates=([Path(replay['history_bundle'])] if replay else [])+[a.parent.parent/'follow-ups/plan-judge-followup-20261026/deepseek/history/history-bundle.json',a.parent.parent/'follow-ups/runtime-judge-review-20261026/real-attempt-20261027-a1/deepseek/history/history-bundle.json'])
 finally:
  runner.verify_parent();write_json(a.out/'budget-summary.json',attempt.inspect())
if __name__=='__main__':main()
