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
def run_judge_attempt(run_path,out,config,*,mode,scorer_config,semantic_goals=False,representation=None,mock_replies=None,max_requests=4,authorize_real=False,passes=('response','trajectory'),prior_attempt=None,trajectory_view_override=None):
 from copy import deepcopy
 from trustfork.runtime.dynamic.common import file_hash
 from trustfork.scoring.judge_client import validate_judge_result,prepared_evidence_index
 from trustfork.scoring.annotation_contracts import apply_annotations
 from trustfork.scoring.trajectory_observer import analyze_trajectory
 from trustfork.scoring.dynamic_metrics_v2 import evaluate_process,process_annotation_status
 out=Path(out);run_path=Path(run_path)
 if out.exists():raise DynamicError('judge_output_exists','Choose a new attempt; team remains frozen')
 if not passes or set(passes)-{'response','trajectory'}:raise DynamicError('unknown_judge_pass','Select response and/or trajectory')
 run=read_json(run_path);events=load_events(run_path.parent,run);refs={e['branch_id']+'::'+e['event_id'] for e in events}
 from trustfork.scoring.goal_observer import frozen_workspace
 states=[frozen_workspace(run['prefix_export']),frozen_workspace(run['frozen_export'])]
 for state in states:
  refs.add(state['evidence_ref']);refs.update(state.get('evidence_refs',[]));refs.update(row.get('evidence_ref',state['evidence_ref'])+'#'+path for path,row in state['paths'].items())
 deliveries=extract_formal_deliverables(events,task_id=run['case_id'],allowed_branch_ids={e['branch_id'] for e in events});ids=[d['deliverable_id'] for d in deliveries];refs.update('response://'+d for d in ids)
 from trustfork.scoring.metric_registry import resolve_scoring_profile
 profile=resolve_scoring_profile(run.get('experiment_version'),scorer_config.get('scoring_profile'))
 response=read_json(run_path.parent/'scoring/response_input.json')['data'];trajectory=read_json(run_path.parent/'scoring/trajectory_input.json')['data']
 if trajectory_view_override is not None:
  trajectory=trajectory_view_override
  if trajectory.get('_sanitizer',{}).get('source_events_hash')!=digest(events):raise DynamicError('judge_view_source_mismatch','Derived view must bind the same frozen raw events')
 semantic=semantic_goals or profile=='dynamic-homogeneous-v2'
 goal=load_case(run['case_id'])['goal_spec'] if semantic else None
 bundle=build_judge_bundle(response,trajectory,scoring_profile=profile,goal_spec=goal,annotation_schema=read_json(config_dir()/'annotation.schema.json') if semantic else None)
 binding=config['logical_bindings'][config['judge_binding']]
 if scorer_config.get('judge_binding',config['judge_binding'])!=config['judge_binding']:raise DynamicError('judge_binding_mismatch','Scorer and actual Judge binding must agree')
 prepared={key:prepare_judge_pass(bundle,key,binding=binding,scorer_config=scorer_config,representation=representation) for key in ('response','trajectory')}
 current=[None]
 transport=ProviderTransport(config,mode=mode,journal=out/'judge-requests.jsonl',authorize_real=authorize_real,http=(lambda *unused:mock_replies[current[0]]) if mode=='mock' else None,max_requests=max_requests,kind='judge')
 client=JudgeClient(transport);scorer_hash=scorer_manifest()['manifest_hash']
 source_hash=digest({'run':file_hash(run_path),'events':digest(events),'states':digest(states),'view':digest(trajectory)})
 annotation={'response_judgements':{},'trajectory_judgements':{},'scorer_manifest_hash':scorer_hash,'synthetic':transport.synthetic,'scoring_profile':profile,'judge_passes':{}}
 statuses={};estimate_errors={}
 for key,value in prepared.items():
  write_json(out/(key+'-prepared.json'),value)
  if key=='trajectory' and profile=='dynamic-homogeneous-v2':
   from trustfork.scoring.judge_request import annotation_output_estimate
   try:write_json(out/'trajectory-output-estimate.json',annotation_output_estimate(value,binding))
   except DynamicError as error:
    estimate_errors[key]=error;write_json(out/'trajectory-output-estimate-error.json',error.record())
  identity={'source_hash':source_hash,'run_id':run['run_id'],'request_hash':value['request_hash'],'wire_payload_hash':value['wire_payload_hash'],
   'scorer_config_hash':digest({'profile':profile,'execution_scope':scorer_config.get('execution_scope','formal'),
    'parameters':value['request']['parameters'],'representation':value['representation']}),'scorer_manifest_hash':scorer_hash,'binding_hash':digest(binding),'synthetic':transport.synthetic}
  statuses[key]={'status':'pending','reason':'not_selected' if key not in passes else 'not_started','identity':identity,'judge_binding':config['judge_binding'],'source_run_id':run['run_id']}
 # Validate every explicitly requested reuse before sending anything. Other pending/failed passes need no prior.
 reuse={}
 if prior_attempt is not None:
  prior=Path(prior_attempt);old_states=read_json(prior/'pass-states.json')
  for key,value in prepared.items():
   if old_states.get(key,{}).get('status')!='completed':continue
   old=old_states[key]
   if old.get('identity')!=statuses[key]['identity']:raise DynamicError('judge_prior_pass_mismatch','Prior source, view, scorer, model or parameters differ')
   saved=read_json(prior/(key+'-result.json'))
   if digest(saved)!=old.get('result_hash') or saved.get('original_request_hash',saved.get('request_hash'))!=value['request_hash']:raise DynamicError('judge_prior_pass_mismatch','Prior result identity differs')
   from trustfork.scoring.judge_contract import validate_complete_result
   validate_complete_result(saved['result'],pass_name=key,response_ids=ids,evidence_refs=refs,scoring_profile=profile,evidence_index=prepared_evidence_index(value),events=events,goal_spec=goal,q=run['q'],prepared=value)
   reuse[key]=saved
 def consume(candidate):
  consumed=apply_annotations(analyze_trajectory(events),candidate,events,goal_spec=goal,evidence_refs=refs,q=run['q'])
  if profile!='dynamic-homogeneous-v2':return None
  process,opportunities=evaluate_process(events,consumed['trajectory'],candidate,run['q'])
  return process_annotation_status(consumed['trajectory'],process,opportunities)
 def save():
  write_json(out/'pass-states.json',statuses);write_json(out/'partial_annotations.json',annotation)
 for key,value in prepared.items():
  current[0]=key;state=statuses[key]
  if value['not_applicable']:
   state.update(status='not_applicable',reason='No formal deliveries')
   write_json(out/(key+'-result.json'),{'status':'not_applicable','reason':'No formal deliveries'});save();continue
  if key not in passes and key not in reuse:save();continue
  if key in estimate_errors:
   error=estimate_errors[key];state.update(status='blocked',reason=error.code,error=error.record());save();continue
  result=reuse.get(key)
  if result is None:
   try:
    report=client.preflight(value);write_json(out/(key+'-preflight.json'),report)
    if transport.count>=max_requests:raise DynamicError('judge_request_budget_blocked','Independent request ceiling exhausted; other pass results retained')
   except DynamicError as error:
    state.update(status='blocked',reason=error.code,error=error.record());write_json(out/(key+'-error.json'),error.record());save();continue
   try:result=client.send_with_repair({**value,'behavior_run_id':run['run_id']},request_id='judge_'+uuid.uuid4().hex,pass_name=key,response_ids=ids,evidence_refs=refs,validator=consume)
   except DynamicError as error:
    blocked=error.code in ('repair_input_overflow','provider_capacity_blocked','campaign_cost_exhausted','campaign_segment_cost_exhausted','campaign_phase_cost_exhausted','provider_route_paused')
    state.update(status='blocked' if blocked else 'failed',reason=error.code,error=error.record());write_json(out/(key+'-error.json'),error.record());save();continue
  write_json(out/(key+'-result.json'),result)
  candidate=deepcopy(annotation)
  try:
   for name,item in result['result'].items():
    if name in candidate and name not in ('response_judgements','trajectory_judgements') and candidate[name]!=item:raise DynamicError('judge_pass_conflict',name)
    candidate[name]=item
   consume(candidate)
  except DynamicError as error:
   state.update(status='failed',reason=error.code,error=error.record());write_json(out/(key+'-error.json'),error.record());save();continue
  candidate['judge_passes'][key]={'prepared':value,'result_hash':digest(result),'semantic_goals':bool(semantic and key=='trajectory'),'synthetic':transport.synthetic}
  annotation=candidate
  state.update(status='completed',reason='validated_pass',result_hash=digest(result),reused=key in reuse)
  if key in reuse:state['prior_attempt']=str(Path(prior_attempt))
  save()
 assessment=consume(annotation)
 write_json(out/'scoring_annotations.json',annotation);save()
 all_done=all(x['status'] in ('completed','not_applicable') for x in statuses.values())
 status='completed' if all_done else 'partial' if any(x['status']=='completed' for x in statuses.values()) else 'blocked' if any(x['status']=='blocked' for x in statuses.values()) else 'failed' if any(x['status']=='failed' for x in statuses.values()) else 'pending'
 result={'status':status,'judge_attempts':transport.count,'synthetic':transport.synthetic,'formal_ready':False,'annotations':'scoring_annotations.json','pass_states':statuses,'process_annotation_status':assessment}
 write_json(out/'attempt-summary.json',result)
 return result

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--mode',choices=['mock','api'],default='mock');p.add_argument('--run',type=Path,required=True);p.add_argument('--bindings',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--scorer-config',type=Path);p.add_argument('--judge-output-budget',type=int);p.add_argument('--request-ceiling',type=int,required=True);p.add_argument('--allow-real-api',action='store_true');p.add_argument('--mock-responses',type=Path);p.add_argument('--semantic-goals',action='store_true');p.add_argument('--passes',nargs='+',choices=['response','trajectory'],default=['response','trajectory']);p.add_argument('--prior-attempt',type=Path);p.add_argument('--trajectory-view',type=Path,help='Explicit source-bound derived view for an audited migration');p.add_argument('--trajectory-representation',choices=['legacy-full','trajectory-lossless-v1','trajectory-lossless-v2']);a=p.parse_args()
 if a.mode=='mock' and not a.mock_responses:p.error('--mock-responses required')
 s=read_json(a.scorer_config or config_dir()/'scorer.example.json')
 if not a.scorer_config:s['scoring_profile']='dynamic-homogeneous-v2' if read_json(a.run).get('experiment_version')=='dynamic-join-homogeneous-v1' else 'legacy-eight-v1'
 if a.judge_output_budget is not None:s.update(response_output_budget_tokens=a.judge_output_budget,trajectory_output_budget_tokens=a.judge_output_budget)
 print(json.dumps(run_judge_attempt(a.run,a.out,read_json(a.bindings),mode=a.mode,scorer_config=s,semantic_goals=a.semantic_goals,representation=a.trajectory_representation,mock_replies=read_json(a.mock_responses) if a.mock_responses else None,max_requests=a.request_ceiling,authorize_real=a.allow_real_api,passes=tuple(a.passes),prior_attempt=a.prior_attempt,trajectory_view_override=read_json(a.trajectory_view) if a.trajectory_view else None)))
if __name__=='__main__':main()
