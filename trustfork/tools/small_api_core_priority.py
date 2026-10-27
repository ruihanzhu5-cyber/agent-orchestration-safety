"""Core-first scoring: original response view and aggregation, no dynamic seed."""
import argparse,copy,json,os,subprocess
from pathlib import Path
from trustfork.tools.small_api_scoring import SmallScoringRunner,scoring_config,ROUND
from trustfork.tools.runtime_judge_review import attach_budget
from trustfork.runtime.dynamic.common import read_json,write_json,file_hash,digest,repo_root,DynamicError
from trustfork.runtime.dynamic.execution_attempt import ExecutionAttempt,migrate_attempts
from trustfork.runtime.dynamic.campaign_budget import CampaignBudget
from trustfork.runtime.dynamic.followup import SEGMENT_ID
from trustfork.runtime.dynamic.artifacts import append_jsonl
from trustfork.scoring.core_contract import CORE,core_bundle
from trustfork.scoring.dynamic_adapter import extract_formal_deliverables,response_judge_view,aggregate_dynamic_scores
from trustfork.scoring.dynamic_pipeline import load_events,scorer_manifest
from trustfork.scoring.judge_request import prepare_judge_pass
from trustfork.scoring.judge_client import JudgeClient
from trustfork.runtime.dynamic.events import events_digest
from trustfork.runtime.dynamic.case_loader import load_case

def response_bundle(view,template,source_events_hash):
 # Reuse the exact validated core rubric/format, never any fixture evidence.
 core=core_bundle(template)
 return {'builder_version':core['builder_version'],'scoring_profile':core['scoring_profile'],
  'evaluation_contract':CORE,'views':{'response':{**view,'evaluation_contract':CORE}},
  'response_ids':[v['response_id'] for v in view['responses']],
  'prompts':{'response':core['prompts']['response']},'formats':{'response':core['formats']['response']},
  'sanitizer':{'version':'core-response-original-extractor-v1','source_events_hash':source_events_hash,'sanitized_view_hash':digest(view)}}

def retained_calibration(parent):
 value=read_json(parent/'trustfork-core-v1-calibration.json')
 if value['gates']!={'response':True,'trajectory':False}:raise DynamicError('core_gate_source_changed','Expected the recorded independent calibration result')
 for row in value['rows']:
  for key in ('source','prepared'):
   if file_hash(Path(row[key]))!=row[key+'_hash']:raise DynamicError('core_calibration_source_changed',row['fixture_id'])
  source=read_json(Path(row['source']))
  if digest(source['oracle'])!=row['oracle_hash']:raise DynamicError('core_oracle_source_changed',row['fixture_id'])
 return value

class CorePriorityRunner(SmallScoringRunner):
 def run_core_source(self,source,tag,behavior_sha,calibration,template):
  source=Path(source);out=self.path/'judges'/CORE/tag;out.mkdir(parents=True,exist_ok=True)
  run=read_json(source);manifest=read_json(source.parent/run['run_manifest_path'])
  if digest(manifest)!=run['run_manifest_hash']:raise DynamicError('run_manifest_hash_mismatch',run['run_id'])
  events=load_events(source.parent,run)
  deliverables=extract_formal_deliverables(events,task_id=run['case_id'],allowed_branch_ids={e['branch_id'] for e in events})
  view=response_judge_view(deliverables,task=load_case(run['case_id'])['public_packet'],events=events)
  bundle=response_bundle(view,template,events_digest(events));cfg=scoring_config(CORE)
  prepared=prepare_judge_pass(bundle,'response',binding=self.config['logical_bindings']['deepseekflash'],scorer_config=cfg)
  prepared['behavior_run_id']=run['run_id'];write_json(out/'prepared.json',prepared);write_json(out/'formal-deliverables.json',deliverables)
  refs={e['branch_id']+'::'+e['event_id'] for e in events}|{'response://'+v['deliverable_id'] for v in deliverables}
  stage='core-response/'+tag;transport=self.transport(stage,out,kind='judge',limit=2)
  # SmallScoringRunner.transport already binds the original shared Judge group.
  def once():
   if prepared['not_applicable']:return {'status':'not_applicable','result':{'response_judgements':{}},'requests':0}
   try:
    result=JudgeClient(transport).send_with_repair(prepared,request_id=self.attempt.request_id(stage,'judge'),pass_name='response',response_ids=bundle['response_ids'],evidence_refs=refs,validation_context={'events':events})
    write_json(out/'result.json',result)
    return {'status':'completed','result':result['result'],'requests':transport.count}
   except (DynamicError,OSError,TimeoutError) as error:
    record=error.record() if isinstance(error,DynamicError) else {'code':type(error).__name__,'reason':str(error)}
    write_json(out/'error.json',record);append_jsonl(self.path/'judge-failures.jsonl',{'stage':stage,'error':record})
    return {'status':'failed','result':{'response_judgements':{}},'requests':transport.count,'reason':getattr(error,'code',type(error).__name__)}
  result=self.attempt.run(stage,{'run_id':run['run_id'],'run_manifest_hash':run['run_manifest_hash'],'request_hash':prepared['request_hash'],'evaluation_contract':CORE},once,artifacts=lambda v:[out/'prepared.json',out/'formal-deliverables.json']+list(out.glob('result.json'))+list(out.glob('error.json')))
  metrics=aggregate_dynamic_scores(deliverables,result['result']['response_judgements'],{},assignment_ids={v['response_id'] for v in view['responses'] if v['assignment'] is not None})
  for name in ('TH','TUL'):metrics['scores'][name]['reason']='Independent core trajectory calibration failed; no real trajectory score sent'
  for record in metrics['scores'].values():record['scorer_manifest_hash']=self.scorer_hash
  metrics['formal_deliverables']=deliverables;metrics['goal_observations']={}
  value={'tag':tag,'source':str(source),'behavior_execution_sha':behavior_sha,'scoring_execution_sha':self.code,'status':'partial','states':{'response':{k:v for k,v in result.items() if k!='result'},'trajectory':{'status':'not_started','reason':'independent_calibration_gate_failed'}},'metrics':metrics,'source_run_manifest_hash':run['run_manifest_hash'],'prepared':str(out/'prepared.json'),'requests':result['requests']}
  write_json(out/'core-metrics.json',value)
  print(json.dumps({'phase':'core-result','tag':tag,'response_status':result['status'],'requests':result['requests'],'scores':{k:metrics['scores'][k] for k in ('RTF','RSR','TH','TUL')}}),flush=True)
  return value

def main():
 p=argparse.ArgumentParser();p.add_argument('--parent',type=Path,required=True);p.add_argument('--behavior-dir',type=Path,required=True);p.add_argument('--calibration-parent',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--attempt-id',required=True);p.add_argument('--bindings',type=Path,required=True);p.add_argument('--env-file',type=Path,required=True);p.add_argument('--allow-real-api',action='store_true');a=p.parse_args()
 if not a.allow_real_api:p.error('Explicit scoring authorization required')
 code=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo_root(),text=True).strip()
 if subprocess.check_output(['git','status','--porcelain=v1','--','trustfork','tests'],cwd=repo_root(),text=True).strip():raise DynamicError('execution_source_dirty','Commit core-priority entry point before scoring')
 accepted=read_json(a.out.parent/'core-priority-acceptance.json')
 if accepted['execution_code_sha']!=code or accepted['request_equivalence']!='passed':raise DynamicError('core_request_equivalence_required','Original fixture wire requests must match exactly')
 calibration=retained_calibration(a.calibration_parent);template=read_json(Path(calibration['rows'][0]['source']))['bundle']
 c=attach_budget(read_json(a.bindings),a.parent);c.update(mode='api',real_api_enabled=True,execution_scope='engineering_smoke')
 dry=migrate_attempts(a.parent/'campaign-budget.sqlite3',apply=False);budget=CampaignBudget(a.parent/'campaign-budget.sqlite3',campaign_id='first-api-20261026',must_exist=True,segment_id=SEGMENT_ID,segment_cny=dry['segment_ceiling_micro_cny']/1e6,segment_identity=dry['segment_identity'])
 attempt=ExecutionAttempt(budget,a.out,attempt_id=a.attempt_id,parent_attempt=read_json(a.calibration_parent/'execution-attempt.json')['attempt_id'],identity={'execution_code_sha':code,'config_hash':digest(c),'behavior_results_hash':file_hash(a.behavior_dir/'behavior-results.json'),'calibration_hash':file_hash(a.calibration_parent/'trustfork-core-v1-calibration.json'),'allowed_actions':['original-core-response','retained-trajectory-gate'],'reason':'User prioritized inherited core metrics and requested removal of unnecessary repeated hashing; no dynamic seed, trajectory encoding, cloned raw logs or calibration resampling'})
 runner=CorePriorityRunner(a.parent,attempt,c,a.behavior_dir);write_json(a.out/'resolved-config.json',c);write_json(a.out/'trustfork-core-v1-calibration.json',calibration)
 write_json(a.out/'plan.json',{'version':'core-priority-v1','scoring_execution_sha':code,'behavior_execution_shas':runner.behaviors.get('behavior_execution_shas'),'calibration_source_hash':file_hash(a.calibration_parent/'trustfork-core-v1-calibration.json'),'calibration_reused_without_resampling':True,'core_contract':CORE,'response_view':'original response_judge_view','aggregation':'original aggregate_dynamic_scores','trajectory_gate':False,'dynamic_extensions':'deferred until core table is available','judge_limit':48,'judge_cny_limit':10,'round_cny_limit':50,'original_campaign_cny_limit':100})
 from dotenv import dotenv_values
 key=dotenv_values(a.env_file).get(c['logical_bindings']['deepseekflash']['key_env'])
 if not key:raise DynamicError('missing_provider_credential','Existing official key unavailable')
 os.environ[c['logical_bindings']['deepseekflash']['key_env']]=key
 try:
  new=[];old=[]
  for row in runner.behaviors['results']:
   value=runner.run_core_source(row['path'],'new-'+row['protocol']+'-'+row['condition'],row['behavior_execution_sha'],calibration,template);new.append(value);write_json(a.out/'new-core-results.json',{'results':new})
  for row in sorted(runner.runs,key=lambda v:(v['protocol']!='F',v['condition']!='HP')):
   value=runner.run_core_source(row['path'],'old-gpt-'+row['protocol']+'-'+row['condition'],'6cfb3a34b95d14a4b35873b5068aba5dafa398b4',calibration,template);old.append(value);write_json(a.out/'old-gpt-core-results.json',{'results':old})
  write_json(a.out/'scoring-results.json',{'status':'partial','core_calibration':calibration,'new_core':new,'old_gpt_core':old,'extended':[],'extended_calibration':{'status':'not_started','reason':'user_core_priority'},'model_requests':0,'scoring_execution_sha':code})
 finally:runner.verify_parent();write_json(a.out/'budget-summary.json',attempt.inspect())
if __name__=='__main__':main()
