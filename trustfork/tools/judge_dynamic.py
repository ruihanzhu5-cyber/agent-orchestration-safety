"""Prepare all frozen Judge passes before any independent mock/API attempt."""
import argparse,json,uuid
from pathlib import Path
from trustfork.runtime.dynamic.common import read_json,write_json,DynamicError,digest,config_dir
from trustfork.runtime.dynamic.provider import ProviderTransport
from trustfork.runtime.dynamic.case_loader import load_case
from trustfork.scoring.judge_client import JudgeClient
from trustfork.scoring.judge_request import build_judge_bundle,prepare_judge_pass
from trustfork.scoring.dynamic_pipeline import load_events,scorer_manifest
from trustfork.scoring.dynamic_adapter import extract_formal_deliverables
def run_judge_attempt(run_path,out,config,*,mode,scorer_config,semantic_goals=False,representation=None,mock_replies=None,max_requests=2,authorize_real=False,passes=('response','trajectory'),prior_attempt=None):
 out=Path(out);run_path=Path(run_path)
 if out.exists():raise DynamicError('judge_output_exists','Choose a new attempt; team remains frozen')
 run=read_json(run_path);events=load_events(run_path.parent,run);refs={e['branch_id']+'::'+e['event_id'] for e in events}
 from trustfork.scoring.goal_observer import frozen_workspace
 for state in (frozen_workspace(run['prefix_export']),frozen_workspace(run['frozen_export'])):
  refs.add(state['evidence_ref']);refs.update(state.get('evidence_refs',[]));refs.update(row.get('evidence_ref',state['evidence_ref'])+'#'+path for path,row in state['paths'].items())
 deliveries=extract_formal_deliverables(events,task_id=run['case_id'],allowed_branch_ids={e['branch_id'] for e in events});ids=[d['deliverable_id'] for d in deliveries];refs.update('response://'+d for d in ids)
 profile=scorer_config.get('scoring_profile') or ('dynamic-homogeneous-v2' if run.get('experiment_version')=='dynamic-join-homogeneous-v1' else 'legacy-eight-v1')
 response=read_json(run_path.parent/'scoring/response_input.json')['data'];trajectory=read_json(run_path.parent/'scoring/trajectory_input.json')['data']
 semantic=semantic_goals or profile=='dynamic-homogeneous-v2'
 bundle=build_judge_bundle(response,trajectory,scoring_profile=profile,goal_spec=load_case(run['case_id'])['goal_spec'] if semantic else None,annotation_schema=read_json(config_dir()/'annotation.schema.json') if semantic else None)
 binding=config['logical_bindings'][config['judge_binding']]
 prepared={key:prepare_judge_pass(bundle,key,binding=binding,scorer_config=scorer_config,representation=representation) for key in ('response','trajectory')}
 current=[None]
 transport=ProviderTransport(config,mode=mode,journal=out/'judge-requests.jsonl',authorize_real=authorize_real,http=(lambda *unused:mock_replies[current[0]]) if mode=='mock' else None,max_requests=max_requests,kind='judge')
 client=JudgeClient(transport);annotation={'response_judgements':{},'trajectory_judgements':{},'scorer_manifest_hash':scorer_manifest()['manifest_hash'],'synthetic':transport.synthetic,'scoring_profile':profile,'judge_passes':{}}
 for key,value in prepared.items():write_json(out/(key+'-prepared.json'),value)
 try:
  for key,value in prepared.items():
   if key in passes:client.preflight(value)
 except DynamicError as error:
  write_json(out/'preflight-error.json',error.record());raise
 for key,value in prepared.items():
  current[0]=key
  if key not in passes and not value['not_applicable']:
   if prior_attempt is None:raise DynamicError('judge_prior_pass_required','Retry only failed passes with an explicit prior attempt')
   prior=Path(prior_attempt);stored=read_json(prior/(key+'-prepared.json'));saved=read_json(prior/(key+'-result.json'))
   if stored['request_hash']!=value['request_hash'] or stored['wire_payload_hash']!=value['wire_payload_hash'] or saved['request_hash']!=value['request_hash'] or saved['synthetic']!=transport.synthetic:raise DynamicError('judge_prior_pass_mismatch','Prior successful pass must bind the exact request and provenance')
   from trustfork.scoring.judge_client import validate_judge_result
   validate_judge_result(saved['result'],pass_name=key,response_ids=ids,evidence_refs=refs,scoring_profile=profile)
   annotation.update(saved['result']);annotation['judge_passes'][key]={'prepared':value,'result_hash':digest(saved),'semantic_goals':False,'synthetic':transport.synthetic,'prior_attempt_result_hash':digest(saved)}
   continue
  if value['not_applicable']:
   write_json(out/(key+'-result.json'),{'status':'not_applicable','reason':'No formal deliveries'});continue
  try:result=client.send(value,request_id='judge_'+uuid.uuid4().hex,pass_name=key,response_ids=ids,evidence_refs=refs)
  except DynamicError as error:
   write_json(out/(key+'-error.json'),error.record());write_json(out/'partial_annotations.json',annotation);raise
  annotation['judge_passes'][key]={'prepared':value,'result_hash':digest(result),'semantic_goals':bool(semantic and key=='trajectory'),'synthetic':transport.synthetic}
  write_json(out/(key+'-result.json'),result)
  for name,item in result['result'].items():
   if name in annotation and name not in ('response_judgements','trajectory_judgements') and annotation[name]!=item:raise DynamicError('judge_pass_conflict',name)
   annotation[name]=item
  write_json(out/'partial_annotations.json',annotation)
 from trustfork.scoring.annotation_contracts import apply_annotations
 from trustfork.scoring.trajectory_observer import analyze_trajectory
 consumed=apply_annotations(analyze_trajectory(events),annotation,events,goal_spec=load_case(run['case_id'])['goal_spec'],evidence_refs=refs,q=run['q'])
 if profile=='dynamic-homogeneous-v2':
  from trustfork.scoring.dynamic_metrics_v2 import evaluate_process
  evaluate_process(events,consumed['trajectory'],annotation,run['q'])
 write_json(out/'scoring_annotations.json',annotation)
 return {'judge_attempts':transport.count,'synthetic':transport.synthetic,'formal_ready':False,'annotations':'scoring_annotations.json'}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--mode',choices=['mock','api'],default='mock');p.add_argument('--run',type=Path,required=True);p.add_argument('--bindings',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--scorer-config',type=Path);p.add_argument('--judge-output-budget',type=int);p.add_argument('--request-ceiling',type=int,required=True);p.add_argument('--allow-real-api',action='store_true');p.add_argument('--mock-responses',type=Path);p.add_argument('--semantic-goals',action='store_true');p.add_argument('--passes',nargs='+',choices=['response','trajectory'],default=['response','trajectory']);p.add_argument('--prior-attempt',type=Path);p.add_argument('--trajectory-representation',choices=['legacy-full','trajectory-lossless-v1']);a=p.parse_args()
 if a.mode=='mock' and not a.mock_responses:p.error('--mock-responses required')
 s=read_json(a.scorer_config or config_dir()/'scorer.example.json')
 if not a.scorer_config:s['scoring_profile']='dynamic-homogeneous-v2' if read_json(a.run).get('experiment_version')=='dynamic-join-homogeneous-v1' else 'legacy-eight-v1'
 if a.judge_output_budget is not None:s.update(response_output_budget_tokens=a.judge_output_budget,trajectory_output_budget_tokens=a.judge_output_budget)
 print(json.dumps(run_judge_attempt(a.run,a.out,read_json(a.bindings),mode=a.mode,scorer_config=s,semantic_goals=a.semantic_goals,representation=a.trajectory_representation,mock_replies=read_json(a.mock_responses) if a.mock_responses else None,max_requests=a.request_ceiling,authorize_real=a.allow_real_api,passes=tuple(a.passes),prior_attempt=a.prior_attempt)))
if __name__=='__main__':main()
