"""Inspect/reconcile/resume one bounded reviewed attempt; no automatic legacy replay."""
import argparse,copy,json,os,sqlite3,subprocess
from pathlib import Path
from trustfork.runtime.dynamic.common import DynamicError,read_json,write_json,digest,file_hash,repo_root,config_dir
from trustfork.runtime.dynamic.artifacts import atomic_json
from trustfork.runtime.dynamic.execution_attempt import ExecutionAttempt,migrate_attempts
from trustfork.runtime.dynamic.campaign_budget import CampaignBudget
from trustfork.runtime.dynamic.followup import parent_sources,clone_frozen_run,SEGMENT_ID
from trustfork.runtime.dynamic.provider import ProviderTransport
from trustfork.scoring.formal_judge_fixtures import make_fixture,check_fixture,make_absent_fixture,check_absent_fixture,make_response_fixture,check_response_fixture,VERSION as FIXTURE_VERSION
from trustfork.scoring.judge_request import prepare_judge_pass
from trustfork.scoring.judge_client import JudgeClient
from trustfork.scoring.dynamic_pipeline import scorer_manifest
REVIEW_ID='runtime-judge-review-20261026'
BASELINE='d68a3a871adcd16688d66b5ec39a67de977176f9'

def scorer(representation='trajectory-lossless-v2'):
 return {'scoring_profile':'dynamic-homogeneous-v2','judge_binding':'deepseekflash','execution_scope':'engineering_smoke','temperature':None,'response_output_budget_tokens':16384,'trajectory_output_budget_tokens':65536,'length_calibration_output_tokens':131072,'trajectory_representation':representation}

def attach_budget(config,parent):
 """Read existing identity; never construct a new budget bucket from new code identity."""
 cfg=copy.deepcopy(config);path=Path(parent)/'campaign-budget.sqlite3'
 with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as db:
  row=db.execute('SELECT ceiling,identity FROM segments WHERE segment_id=?',(SEGMENT_ID,)).fetchone()
 if row is None or row[0]!=20000000:raise DynamicError('execution_segment_bucket_mismatch','Existing CNY20 bucket missing or changed')
 cfg['campaign_budget'].update(path=str(path),campaign_id='first-api-20261026',must_exist=True,segment_id=SEGMENT_ID,segment_cny=20,segment_identity=json.loads(row[1]))
 return cfg

class ReviewRunner:
 def __init__(self,parent,attempt,config,*,mode='api',http_factory=None):
  self.parent,self.attempt,self.path=Path(parent),attempt,attempt.path
  self.config=copy.deepcopy(config);self.mode,self.http_factory=mode,http_factory
  self.seal,self.runs=parent_sources(self.parent)
  self.suspended_passes=set()
  self.code=attempt.identity['execution_code_sha'];self.scorer_hash=scorer_manifest()['manifest_hash']
 def transport(self,stage,out,*,kind='judge',limit=3,formal=False):
  cfg=copy.deepcopy(self.config);cfg['campaign_budget']['phase']='interface_probe' if formal else 'engineering_smoke'
  from trustfork.runtime.dynamic.experiment_config import resolve_experiment
  experiment=resolve_experiment('p001',team_model='deepseekflash',judge_binding=cfg['judge_binding']) if kind=='model' else None
  t=ProviderTransport(cfg,mode=self.mode,journal=Path(out)/('provider-requests.jsonl' if kind=='model' else 'judge-requests.jsonl'),authorize_real=self.mode=='api',max_requests=limit,kind=kind,experiment=experiment,http=self.http_factory(stage) if self.http_factory else None)
  t.execution_context={'execution_attempt_id':self.attempt.attempt_id,'execution_stage_id':stage,'execution_review_id':REVIEW_ID}
  if kind=='model':t.execution_context['model_generation_group_id']=REVIEW_ID+'/'+stage
  if formal:t.execution_context.update(validation_group_id=REVIEW_ID+'/formal',group_request_limit=24)
  t.request_namespace=self.attempt.request_id(stage,'model')
  return t
 def freeze_plan(self):
  target=self.path/'formal-plan.json'
  if target.exists():
   plan=read_json(target)
   if plan['code_sha']!=self.code or plan['scorer_hash']!=self.scorer_hash or plan['config_hash']!=digest(self.config):raise DynamicError('formal_plan_identity_mismatch','Frozen plan belongs to different execution')
   for row in plan['cases']:
    if file_hash(Path(row['source_path']))!=row['source_file_hash'] or file_hash(Path(row['prepared_path']))!=row['prepared_file_hash']:raise DynamicError('formal_plan_source_changed','Frozen fixture/prepared input changed')
   return plan
  cases=[]
  for kind in ('direct_failed_attempt','chain_rejection_missing','no_opportunity','response_success','response_refusal','queued_only'):
   directory=self.path/'fixtures'/kind;directory.mkdir(parents=True,exist_ok=False)
   fixture=make_fixture(directory,kind) if kind in ('direct_failed_attempt','chain_rejection_missing') else make_absent_fixture(directory) if kind=='no_opportunity' else make_response_fixture(directory,kind)
   source=directory/'source.json';write_json(source,fixture)
   pass_name=fixture.get('pass_name','trajectory')
   for rep in (('trajectory-lossless-v1','trajectory-lossless-v2') if pass_name=='trajectory' else ('legacy-full',)):
    out=directory/rep;prepared=prepare_judge_pass(fixture['bundle'],pass_name,binding=self.config['logical_bindings'][self.config['judge_binding']],scorer_config=scorer(rep))
    # Oracle is retained separately; only the bundle enters the actual Judge wire.
    if 'oracle' in prepared['wire_payload']['messages'][1]['content']:raise DynamicError('fixture_oracle_leak','Oracle key must not be Judge visible')
    path=out/'prepared.json';write_json(path,prepared)
    cases.append({'case_id':kind+'/'+rep,'fixture_id':kind,'pass_name':pass_name,'representation':rep,'source_hash':fixture['source_hash'],'oracle_hash':digest(fixture['oracle']),'source_path':str(source),'source_file_hash':file_hash(source),'prepared_path':str(path),'prepared_file_hash':file_hash(path),'request_hash':prepared['request_hash'],'not_applicable':prepared['not_applicable'],'scorer_hash':self.scorer_hash,'schema_hash':file_hash(config_dir()/'annotation.schema.json'),'fixture_version':FIXTURE_VERSION,'fixture_code_hash':file_hash(repo_root()/'trustfork/scoring/formal_judge_fixtures.py'),'scorer_config_hash':prepared['scorer_config_hash'],'config_hash':digest(self.config)})
  plan={'version':'runtime-review-formal-plan-v1','code_sha':self.code,'scorer_hash':self.scorer_hash,'config_hash':digest(self.config),'actual_request_limit':24,'per_pass_request_limit':3,'cases':cases}
  write_json(target,plan);return plan
 def formal(self):
  plan=self.freeze_plan();rows=[];blocked=set()
  for case in plan['cases']:
   stage='formal/'+case['case_id'];out=Path(case['prepared_path']).parent
   def run_case():
    if case['not_applicable']:value={'status':'not_applicable','passed':True,'reason':'queued_receipt_is_not_formal_response','requests':0}
    elif case['pass_name'] in blocked:
     value={'status':'not_started','passed':False,'reason':'same_capability_formal_gate_failed','requests':0}
    else:
     t=self.transport(stage,out,formal=True)
     f=read_json(Path(case['source_path']));prepared=read_json(Path(case['prepared_path']))
     try:
      result=JudgeClient(t).send_with_repair({**prepared,'behavior_run_id':'formal-'+case['fixture_id']},request_id=self.attempt.request_id(stage,'judge'),pass_name=case['pass_name'],response_ids=f['bundle']['response_ids'],evidence_refs={e['branch_id']+'::'+e['event_id'] for e in f['events']}|{'response://'+i for i in f['bundle']['response_ids']},validation_context={'events':f['events']})
      write_json(out/'result.json',result)
      checked=check_response_fixture(f,result['result']) if case['pass_name']=='response' else check_absent_fixture(f,result['result']) if f['fixture_id']=='no_opportunity' else check_fixture(f,result['result'])
      write_json(out/'fact-check.json',checked)
      value={'status':'completed' if checked['passed'] else 'failed','passed':checked['passed'],'checks':checked['checks'],'reason':None if checked['passed'] else 'formal_facts_failed','requests':t.count,'result_hash':digest(result)}
     except (DynamicError,OSError,TimeoutError) as error:
      value={'status':'blocked' if getattr(error,'code','').endswith(('exhausted','blocked','overflow')) else 'failed','passed':False,'reason':getattr(error,'code',type(error).__name__),'requests':t.count,'error':error.record() if isinstance(error,DynamicError) else str(error)}
      write_json(out/'error.json',value)
    value.update({k:case[k] for k in ('case_id','fixture_id','pass_name','representation','source_hash','oracle_hash','scorer_hash','schema_hash','fixture_version','fixture_code_hash','scorer_config_hash','config_hash')})
    write_json(out/'acceptance.json',value);return value
   value=self.attempt.run(stage,case,run_case,artifacts=lambda result:[out/'acceptance.json',Path(case['source_path']),Path(case['prepared_path'])]+[p for p in out.glob('*.json') if p.name not in ('prepared.json','acceptance.json')])
   if not value['passed'] and not case['not_applicable']:blocked.add(case['pass_name'])
   rows.append(value);print(json.dumps({'phase':'formal',**{k:value[k] for k in ('case_id','status','passed','requests','reason') if k in value}}),flush=True)
   write_json(self.path/'formal-judge-acceptance.json',{'cases':rows,'status':'running','plan_hash':digest(plan)})
  gates={}
  for pass_name in ('response','trajectory'):
   required=[r for r in rows if r['pass_name']==pass_name and r['status']!='not_applicable']
   gates[pass_name]=bool(required) and all(r['passed'] for r in required)
  result={'status':'completed' if all(gates.values()) else 'blocked','gates':gates,'cases':rows,'plan_hash':digest(plan),'code_sha':self.code,'scorer_hash':self.scorer_hash,'actual_requests':sum(r['requests'] for r in rows),'limit':24,'calibration_and_repair_are_separate':True}
  write_json(self.path/'formal-judge-acceptance.json',result);return result
 def verify_parent(self):
  if parent_sources(self.parent)[0]!=self.seal:raise DynamicError('followup_parent_changed','Old four behaviors or campaign markers changed')
 def score_frozen(self,path,out,gates):
  from trustfork.tools.judge_dynamic import run_judge_attempt
  from trustfork.scoring.scoring_versions import rescore_contract,frozen_identity
  from trustfork.scoring.dynamic_pipeline import score_run
  path,out=Path(path),Path(out);source=frozen_identity(path);previous=None;passes={}
  cfg=copy.deepcopy(self.config);cfg['campaign_budget']['phase']='engineering_smoke'
  for name in ('response','trajectory'):
   if not gates.get(name) or name in self.suspended_passes:passes[name]={'status':'blocked','reason':'formal_or_prior_engineering_'+name+'_gate'};continue
   stage='score/'+read_json(path)['run_id']+'/'+name;target=out/name
   def run_pass():
    value=run_judge_attempt(path,target,cfg,mode=self.mode,scorer_config=scorer(),max_requests=3,authorize_real=self.mode=='api',passes=(name,),prior_attempt=previous,request_namespace=self.attempt.request_id(stage,'judge'),execution_context={'execution_attempt_id':self.attempt.attempt_id,'execution_stage_id':stage,'execution_review_id':REVIEW_ID},mock_http=self.http_factory(stage) if self.http_factory else None)
    return {'status':value['pass_states'][name]['status'],'summary_path':str(target/'attempt-summary.json'),'annotations_path':str(target/'scoring_annotations.json'),'out':str(target),'pass_state':value['pass_states'][name]}
   saved=self.attempt.run(stage,{'source':source,'scorer':self.scorer_hash,'scorer_config':scorer(),'pass_name':name},run_pass,artifacts=lambda r:[Path(r['summary_path']),Path(r['annotations_path']),target/'pass-states.json'])
   passes[name]=saved['pass_state'];previous=saved['out']
   # Publish each successful independent pass before attempting the next one.
   if saved['status'] in ('completed','not_applicable'):
    metrics_file=out/(name+'-metrics.json');aggregate_stage='aggregate/'+read_json(path)['run_id']+'/'+name
    def publish_metrics():
     contract=rescore_contract(path,reason='Reviewed fixed frozen behavior; independent completed pass and new scorer',annotation_policy='new',new_annotations=Path(saved['annotations_path']))
     summary=score_run(path,mode='engineering-smoke' if self.mode=='api' else 'test-fixtures',rescore=contract)
     write_json(metrics_file,summary);return {'status':'completed','path':str(metrics_file)}
    published=self.attempt.run(aggregate_stage,{'source':source,'annotations_hash':file_hash(Path(saved['annotations_path'])),'scorer':self.scorer_hash},publish_metrics,artifacts=lambda v:[Path(v['path'])])
    write_json(out/'latest-metrics.json',read_json(Path(published['path'])))
   if saved['status'] not in ('completed','not_applicable'):self.suspended_passes.add(name)
  self.verify_parent()
  return {'run_id':read_json(path)['run_id'],'path':str(path),'pass_states':passes,'metrics_path':str(out/'latest-metrics.json') if (out/'latest-metrics.json').exists() else None,'status':'completed' if all(passes.get(k,{}).get('status') in ('completed','not_applicable') for k in ('response','trajectory')) else 'partial' if any(v.get('status')=='completed' for v in passes.values()) else 'blocked'}
 def rescore(self,gates):
  rows=[]
  for row in sorted(self.runs,key=lambda r:((0 if r['protocol']=='F' else 1),(0 if r['condition']=='HP' else 1))):
   if not any(gates.values()):value={'status':'not_started','reason':'formal_judge_gates_failed','run_id':row['run_id']}
   else:
    stage='clone/'+row['protocol']+'/'+row['condition'];dest=self.path/'gpt-rescore'/(row['protocol']+'-'+row['condition'])
    saved=self.attempt.run(stage,{'source':self.seal['runs'][row['run_id']]['frozen_identity']},lambda:{'path':str(clone_frozen_run(row['path'],dest))},artifacts=lambda r:[Path(r['path']),dest/'copy-manifest.json'])
    try:value=self.score_frozen(Path(saved['path']),dest/'judge-review',gates)
    except (DynamicError,OSError,TimeoutError) as error:value={'status':'blocked','reason':getattr(error,'code',type(error).__name__),'error':str(error),'run_id':row['run_id']}
   value.update(protocol=row['protocol'],condition=row['condition'],behavior_execution_sha='6cfb3a34b95d14a4b35873b5068aba5dafa398b4',scoring_execution_sha=self.code,new_team_requests=0)
   rows.append(value);write_json(self.path/'gpt-rescore-results.json',{'results':rows});print(json.dumps({'phase':'old-gpt',**{k:value[k] for k in ('protocol','condition','status','reason') if k in value}}),flush=True)
   # An engineering failure suspends dependent scoring; never repeat the same error on long inputs.
   if value.get('reason'):gates={k:False for k in gates}
  return {'status':'completed' if all(r['status']=='completed' for r in rows) else 'partial','results':rows,'new_team_requests':0}
 def deepseek(self,gates):
  from trustfork.agents.pi_dynamic import PiDynamic,ProviderSource
  from trustfork.runtime.dynamic.prepared_artifacts import prepare_history,load_history,save_prefix,load_prefix,history_contract
  from trustfork.scoring.dynamic_pipeline import score_run
  gates={k:v and k not in self.suspended_passes for k,v in gates.items()}
  if not all(gates.values()):
   result={'status':'not_started','reason':'formal_judge_gates_failed','results':[{'protocol':p,'condition':c,'status':'not_started'} for p in ('S','F') for c in ('HP','HA')]};write_json(self.path/'deepseek-results.json',result);return result
  root=self.path/'deepseek';hout=root/'history';t=self.transport('history',hout,kind='model',limit=240)
  r=PiDynamic('p001',hout,provider=t,team_model='deepseekflash');r.execution_attempt=self.attempt;hpath=hout/'history-bundle.json'
  old=self.parent.parent/'follow-ups/plan-judge-followup-20261026/deepseek/history/history-bundle.json'
  # Compare explicitly; this versioned wait protocol normally requires the authorized new fixed histories.
  if old.exists():
   old_contract=read_json(old)['contract'];write_json(root/'history-compatibility.json',{'compatible':old_contract==history_contract(r),'old_contract_hash':digest(old_contract),'new_contract_hash':digest(history_contract(r)),'old_retained':True})
  if old.exists() and read_json(old)['contract']==history_contract(r):hpath=old
  try:
   if hpath.exists():bundle=read_json(hpath);load_history(r,hpath)
   else:bundle=prepare_history(r,ProviderSource(),hpath)
  except (DynamicError,OSError,TimeoutError) as error:
   result={'status':'blocked','reason':getattr(error,'code',type(error).__name__),'phase':'history','results':[{'protocol':p,'condition':c,'status':'not_started','reason':'history_engineering_stop'} for p in ('S','F') for c in ('HP','HA')]};write_json(self.path/'deepseek-results.json',result);return result
  results=[]
  for protocol in ('S','F'):
   out=root/'blocks'/protocol;stage='prefix/'+protocol;t=self.transport(stage,out,kind='model',limit=240)
   runtime=PiDynamic('p001',out,provider=t,team_model='deepseekflash',protocol=protocol);runtime.execution_attempt=self.attempt;history=load_history(runtime,hpath);prefix_path=out/'prepared-prefix.json'
   def prefix_once():
    prefix=runtime.run_prefix(ProviderSource(),history=history)
    if prefix['status']!='triggered':
     write_json(out/'preparation-outcome.json',prefix);return {'status':prefix['status'],'path':str(out/'preparation-outcome.json')}
    save_prefix(runtime,prefix,prefix_path);return {'status':'completed','path':str(prefix_path),'checkpoint_id':prefix['checkpoint']['checkpoint_id']}
   try:saved=self.attempt.run(stage,{'history_bundle_id':bundle['bundle_id'],'prefix_identity':runtime.prefix_identity()},prefix_once,artifacts=lambda v:[Path(v['path'])])
   except (DynamicError,OSError,TimeoutError) as error:
    results.extend({'protocol':protocol,'condition':c,'status':'not_started','reason':getattr(error,'code',type(error).__name__)} for c in ('HP','HA'));break
   if saved['status']!='completed':
    results.extend({'protocol':protocol,'condition':c,'status':'not_started','reason':'prefix_'+saved['status']} for c in ('HP','HA'));continue
   prefix=load_prefix(runtime,Path(saved['path']))
   for condition in ('HP','HA'):
    stage='t3/'+protocol+'/'+condition;t.execution_context['execution_stage_id']=stage;t.execution_context['model_generation_group_id']=REVIEW_ID+'/'+stage;t.request_namespace=self.attempt.request_id(stage,'model')
    def branch_once():
     run=runtime.run_branch(prefix['checkpoint'],condition,ProviderSource(),attempt=0);path=runtime.directory/'run.json';score_run(path,mode='engineering-smoke' if self.mode=='api' else 'test-fixtures')
     return {'status':run['run_status'],'run_id':run['run_id'],'path':str(path)}
    try:
     run=self.attempt.run(stage,{'checkpoint':prefix['checkpoint']['checkpoint_id'],'condition':condition,'protocol':runtime.prefix_identity()},branch_once,artifacts=lambda v:[Path(v['path']),Path(v['path']).parent/'run_manifest.json',Path(v['path']).parent/'events.jsonl'])
     value={**run,'protocol':protocol,'condition':condition,'judging':self.score_frozen(Path(run['path']),Path(run['path']).parent/'judge-review',gates)}
    except (DynamicError,OSError,TimeoutError) as error:value={'status':'blocked','protocol':protocol,'condition':condition,'reason':getattr(error,'code',type(error).__name__)}
    results.append(value);write_json(self.path/'deepseek-results.json',{'status':'running','history_bundle_id':bundle['bundle_id'],'results':results})
    if value['status']=='blocked' or value.get('judging',{}).get('status')!='completed':break
   if results and (results[-1]['status']=='blocked' or results[-1].get('judging',{}).get('status')!='completed'):break
  done={(v['protocol'],v['condition']) for v in results}
  results.extend({'protocol':p,'condition':c,'status':'not_started','reason':'dependency_or_engineering_stop'} for p in ('S','F') for c in ('HP','HA') if (p,c) not in done)
  result={'status':'completed' if all(r['status']=='valid_behavior' and r.get('judging',{}).get('status')=='completed' for r in results) else 'partial','history_bundle_id':bundle['bundle_id'],'results':results};write_json(self.path/'deepseek-results.json',result);return result

def inspect(path,attempt_id=None):
 path=Path(path)
 with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as db:
  db.row_factory=sqlite3.Row
  tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  attempts=[dict(r) for r in db.execute('SELECT * FROM execution_attempts')] if 'execution_attempts' in tables else []
  if attempt_id:attempts=[r for r in attempts if r['attempt_id']==attempt_id]
  stages=[dict(r) for r in db.execute('SELECT * FROM execution_stages WHERE attempt_id=?',(attempt_id,))] if attempt_id and 'execution_stages' in tables else []
 return {'migration':migrate_attempts(path,apply=False),'attempts':attempts,'stages':stages}

def reconcile_stage(attempt,stage,artifact,kind,identity,*,run_path=None):
 """No sender: only full independently verifiable persisted artifacts can close a stage."""
 from trustfork.runtime.dynamic.checkpoints import validate_checkpoint
 from trustfork.runtime.dynamic.events import EventLedger
 from trustfork.scoring.scoring_versions import frozen_identity
 from trustfork.scoring.judge_contract import validate_complete_result
 artifact=Path(artifact).resolve();root=attempt.path.resolve()
 if root not in artifact.parents:raise DynamicError('reconcile_artifact_scope','Artifact must belong to this preparation attempt')
 if not artifact.is_file():raise DynamicError('reconcile_artifact_missing','No complete persisted artifact')
 value=read_json(artifact);files=[artifact]
 if kind=='history':
  expected_task={'history/H1':'p002','history/H2':'p007'}.get(stage)
  record=value.get('record',{});sessions=value.get('sessions',{})
  if not expected_task or value.get('execution_attempt_id')!=attempt.attempt_id or value.get('stage_identity_hash')!=digest(identity) or record.get('task_id')!=expected_task or set(sessions)!={'Main','A','B'}:raise DynamicError('history_reconcile_identity','Complete actor-scoped task artifact required')
  if any(sessions[a]['config']['actor_id']!=a or sessions[a]['config']['task_id']!=expected_task or digest(sessions[a])!=record['session_hashes'][a] for a in sessions):raise DynamicError('history_session_hash_mismatch','Persisted actor state changed')
  path=artifact.parent/'history-execution.json'
  if read_json(path)!=record:raise DynamicError('history_reconcile_record','History record differs')
  log=artifact.parent/'events.jsonl'
  with log.open() as stream:first=json.loads(next(stream))
  ledger=EventLedger(log,first['branch_id'],expected_task)
  if ledger.content_hash()!=record['request_ledger_hash']:raise DynamicError('history_reconcile_ledger','Exact completed history event boundary required')
  files.extend([path,log]);result={'path':str(artifact),'task_id':expected_task,'status':record['status']}
 elif kind=='prefix':
  snapshot=value['checkpoint'] if value.get('version')=='prepared-prefix-v1' else value
  validate_checkpoint(snapshot)
  bound=snapshot['bindings'].get('execution_attempt')
  if bound!={'attempt_id':attempt.attempt_id,'code_sha':attempt.identity['execution_code_sha']} or snapshot['bindings'].get('prefix_identity')!=identity['prefix_identity'] or snapshot['history'].get('history_bundle_id')!=identity['history_bundle_id']:raise DynamicError('prefix_reconcile_identity','Checkpoint must bind this attempt, code and compatible history')
  if value.get('version')=='prepared-prefix-v1':
   check=dict(value);hashed=check.pop('artifact_hash',None)
   if digest(check)!=hashed:raise DynamicError('prefix_artifact_hash_mismatch','Prepared prefix changed')
   prepared_path=artifact
  else:
   prepared={'version':'prepared-prefix-v1','checkpoint':snapshot,'source_cursor':{'kind':'provider','backend':'mock' if snapshot['synthetic'] else 'api'},'synthetic':snapshot['synthetic']};prepared['artifact_hash']=digest(prepared)
   prepared_path=artifact.with_name('prepared-prefix-reconciled.json');write_json(prepared_path,prepared);files.append(prepared_path)
  result={'status':'completed','path':str(prepared_path),'checkpoint_id':snapshot['checkpoint_id']}
 elif kind=='run':
  if value.get('checkpoint_id')!=identity['checkpoint'] or value.get('condition')!=identity['condition'] or value.get('run_status') not in ('valid_behavior','resource_ended'):raise DynamicError('run_reconcile_incomplete','A complete frozen behavior is required')
  frozen_identity(artifact)
  manifest=artifact.parent/value['run_manifest_path'];events=artifact.parent/value['events_path']
  with events.open() as lines:
   for line in lines:
    e=json.loads(line)
    if e['event_type']=='model_request_submitted' and not e['request_id'].startswith(attempt.request_id(stage,'model')):raise DynamicError('run_reconcile_attempt','Submitted request belongs to another attempt/stage')
  files.extend([manifest,events]);result={'status':value['run_status'],'run_id':value['run_id'],'path':str(artifact)}
 elif kind=='judge':
  from trustfork.scoring.dynamic_pipeline import load_events
  name=stage.rsplit('/',1)[-1];directory=artifact.parent
  states=read_json(directory/'pass-states.json');state=states[name]
  if state['status'] not in ('completed','not_applicable') or state['identity']['scorer_manifest_hash']!=identity['scorer']:raise DynamicError('judge_reconcile_incomplete','Only a validated completed independent pass may be reused')
  if run_path is None or frozen_identity(Path(run_path))!=identity['source']:raise DynamicError('judge_reconcile_source','Supply the unchanged frozen behavior source')
  prepared=read_json(directory/(name+'-prepared.json'));result_file=directory/(name+'-result.json');saved=read_json(result_file)
  if state['status']=='completed':
   if digest(saved)!=state['result_hash'] or saved.get('original_request_hash',saved['request_hash'])!=prepared['request_hash']:raise DynamicError('judge_reconcile_hash','Prepared or actual Judge result changed')
   run=read_json(Path(run_path));events=load_events(Path(run_path).parent,run)
   refs={e['branch_id']+'::'+e['event_id'] for e in events}
   from trustfork.scoring.dynamic_adapter import extract_formal_deliverables
   ids=[r['deliverable_id'] for r in extract_formal_deliverables(events,task_id=run['case_id'])];refs|={'response://'+i for i in ids}
   validate_complete_result(saved['result'],pass_name=name,response_ids=ids,evidence_refs=refs,scoring_profile='dynamic-homogeneous-v2',prepared=prepared,events=events)
  elif not prepared['not_applicable']:raise DynamicError('judge_reconcile_incomplete','Not-applicable must come from empty formal deliveries')
  files.extend([directory/'pass-states.json',result_file,directory/(name+'-prepared.json'),directory/'scoring_annotations.json'])
  result={'status':state['status'],'summary_path':str(artifact),'annotations_path':str(directory/'scoring_annotations.json'),'out':str(directory),'pass_state':state}
 else:raise DynamicError('reconcile_kind_unknown',kind)
 return attempt.reconcile(stage,identity,lambda:result,artifacts=lambda value:files)


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('operation',choices=('inspect','reconcile','resume'));p.add_argument('--parent',type=Path,required=True);p.add_argument('--out',type=Path);p.add_argument('--attempt-id');p.add_argument('--parent-attempt',default=SEGMENT_ID);p.add_argument('--bindings',type=Path);p.add_argument('--env-file',type=Path);p.add_argument('--allow-real-api',action='store_true');p.add_argument('--stage');p.add_argument('--artifact',type=Path);p.add_argument('--kind',choices=('history','prefix','run','judge'));p.add_argument('--run',type=Path);a=p.parse_args()
 ledger=a.parent/'campaign-budget.sqlite3'
 if a.operation=='inspect':print(json.dumps(inspect(ledger,a.attempt_id)));return
 if a.operation=='reconcile':
  if not all((a.out,a.attempt_id,a.stage,a.artifact,a.kind)):p.error('reconcile requires existing out, attempt-id, stage, artifact and kind; no API needed')
  with sqlite3.connect('file:'+str(ledger)+'?mode=ro',uri=True) as db:
   db.row_factory=sqlite3.Row
   row=db.execute('SELECT * FROM execution_attempts WHERE attempt_id=?',(a.attempt_id,)).fetchone()
   start=db.execute("SELECT detail FROM execution_transitions WHERE attempt_id=? AND stage_id=? AND state='started' ORDER BY sequence LIMIT 1",(a.attempt_id,a.stage)).fetchone()
  if row is None or start is None:raise DynamicError('reconcile_stage_unknown','No original attempt/stage identity')
  identity=json.loads(row['identity']);parent=identity.pop('parent_attempt');identity.pop('version');identity.pop('segment_id')
  dry=migrate_attempts(ledger,apply=False);b=CampaignBudget(ledger,campaign_id='first-api-20261026',must_exist=True,segment_id=SEGMENT_ID,segment_cny=20,segment_identity=dry['segment_identity'])
  attempt=ExecutionAttempt(b,a.out,attempt_id=a.attempt_id,parent_attempt=parent,identity=identity)
  print(json.dumps(reconcile_stage(attempt,a.stage,a.artifact,a.kind,json.loads(start['detail']),run_path=a.run)));return
 if not a.allow_real_api or not a.out or not a.bindings or not a.env_file or not a.attempt_id:p.error('resume requires explicit authorization, existing bindings/env, out and attempt-id')
 code=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo_root(),text=True).strip()
 if subprocess.run(['git','merge-base','--is-ancestor',BASELINE,code],cwd=repo_root()).returncode:raise DynamicError('review_baseline_mismatch','Use the reviewed baseline successor')
 if subprocess.run(['git','diff','--quiet','HEAD','--','trustfork','tests'],cwd=repo_root()).returncode or subprocess.check_output(['git','ls-files','--others','--exclude-standard','--','trustfork','tests'],cwd=repo_root(),text=True).strip():raise DynamicError('execution_source_dirty','Commit tested code before paid execution')
 acceptance=read_json(a.out.parent/'offline-acceptance.json')
 if acceptance.get('status')!='passed' or acceptance.get('execution_code_sha')!=code:raise DynamicError('offline_acceptance_required','Exact execution SHA must pass A-D offline gates')
 c=read_json(a.bindings);c.update(mode='api',real_api_enabled=True,execution_scope='engineering_smoke');c=attach_budget(c,a.parent)
 if c['judge_binding']!='deepseekflash' or c['logical_bindings']['deepseekflash'].get('engineering_counting')!='deepseek-v41-text-v1':raise DynamicError('review_binding_mismatch','Keep existing official DeepSeek/high counting route')
 dry=migrate_attempts(ledger,apply=False);write_json(a.out.parent/'resume-dry-run.json',dry)
 if dry['needs_migration']:
  migrated=migrate_attempts(ledger,apply=True,backup=a.out.parent/'ledger-before-runtime-review.sqlite3');write_json(a.out.parent/'ledger-migration.json',migrated)
 b=CampaignBudget(ledger,campaign_id='first-api-20261026',must_exist=True,segment_id=SEGMENT_ID,segment_cny=20,segment_identity=dry['segment_identity'])
 attempt=ExecutionAttempt(b,a.out,attempt_id=a.attempt_id,parent_attempt=a.parent_attempt,identity={'execution_code_sha':code,'config_hash':digest(c),'coordination_contract':__import__('trustfork.runtime.dynamic.coordination_contract',fromlist=['coordination_identity']).coordination_identity(),'scorer_hash':scorer_manifest()['manifest_hash'],'allowed_actions':['formal','old-gpt-rescore','fixed-deepseek'],'retry_reason':'Reviewed deterministic engineering defects; original results retained'})
 write_json(a.out/'resolved-config.json',c);runner=ReviewRunner(a.parent,attempt,c);runner.freeze_plan()
 # The only secret loading in this CLI occurs after all offline gates and exact frozen identity.
 from dotenv import dotenv_values
 values=dotenv_values(a.env_file);binding=c['logical_bindings']['deepseekflash'];key=os.environ.get(binding['key_env']) or values.get(binding['key_env'])
 if not key:raise DynamicError('missing_provider_credential','Existing DeepSeek credential unavailable')
 os.environ[binding['key_env']]=key
 try:
  formal=runner.formal();old=runner.rescore(copy.deepcopy(formal['gates']));new=runner.deepseek(copy.deepcopy(formal['gates']))
  write_json(a.out/'execution-results.json',{'status':'completed' if formal['status']=='completed' and old['status']=='completed' and new['status']=='completed' else 'partial','formal':formal,'old_gpt':old,'deepseek':new,'execution_code_sha':code})
 finally:
  runner.verify_parent();write_json(a.out/'budget-summary.json',attempt.inspect())
if __name__=='__main__':main()
