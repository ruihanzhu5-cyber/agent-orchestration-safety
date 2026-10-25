"""Prepare/send independent Judge passes for frozen runs. Default is local mock."""
import argparse
import json
from pathlib import Path
import uuid
from trustfork.runtime.dynamic.common import read_json,write_json,DynamicError,digest
from trustfork.runtime.dynamic.provider import ProviderTransport
from trustfork.scoring.judge_client import JudgeClient
from trustfork.scoring.judge_request import prepare_judge_request,FORMAT_INSTRUCTIONS
from trustfork.scoring.dynamic_pipeline import load_events,scorer_manifest
from trustfork.scoring.dynamic_adapter import judge_prompts,extract_formal_deliverables
from trustfork.scoring.trajectory_codec import encode_trajectory,VERSION

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',choices=['mock','api'],default='mock')
    p.add_argument('--run',type=Path,required=True);p.add_argument('--bindings',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--judge-output-budget',type=int,required=True)
    p.add_argument('--request-ceiling',type=int,required=True)
    p.add_argument('--allow-real-api',action='store_true')
    p.add_argument('--mock-responses',type=Path,help='Local JSON {response: HTTP_REPLY, trajectory: HTTP_REPLY}')
    p.add_argument('--semantic-goals',action='store_true',help='Include original GoalSpec and versioned observer schema, never condition/private actor goal')
    a=p.parse_args()
    if a.out.exists():raise DynamicError('judge_output_exists','Choose a new Judge attempt; frozen team data stays intact')
    config=read_json(a.bindings);current_pass=[None];replies={}
    if a.mode=='mock':
        if not a.mock_responses:p.error('--mock-responses required in mock mode')
        replies=read_json(a.mock_responses)
    transport=ProviderTransport(config,mode=a.mode,journal=a.out/'judge-requests.jsonl',authorize_real=a.allow_real_api,
        http=(lambda *unused:replies[current_pass[0]]) if a.mode=='mock' else None,max_requests=a.request_ceiling,kind='judge')
    client=JudgeClient(transport);run=read_json(a.run);events=load_events(a.run.parent,run)
    refs={e['branch_id']+'::'+e['event_id'] for e in events}
    from trustfork.scoring.goal_observer import frozen_workspace
    for observation in (frozen_workspace(run['prefix_export']),frozen_workspace(run['frozen_export'])):
        refs.add(observation['evidence_ref']);refs.update(observation.get('evidence_refs',[]))
        refs.update(row.get('evidence_ref',observation['evidence_ref'])+'#'+path for path,row in observation['paths'].items())
    deliveries=extract_formal_deliverables(events,task_id=run['case_id'],allowed_branch_ids={e['branch_id'] for e in events})
    ids=[d['deliverable_id'] for d in deliveries];refs.update('response://'+d for d in ids)
    prompts=judge_prompts(ids);annotation={'response_judgements':{},'trajectory_judgements':{},'scorer_manifest_hash':scorer_manifest()['manifest_hash'],
        'synthetic':transport.synthetic,'judge_passes':{}}
    for pass_name in ('response','trajectory'):
        current_pass[0]=pass_name
        view=read_json(a.run.parent/'scoring'/(pass_name+'_input.json'))['data']
        fmt=FORMAT_INSTRUCTIONS[pass_name]
        if pass_name=='trajectory' and a.semantic_goals:
            from trustfork.runtime.dynamic.case_loader import load_case
            from trustfork.runtime.dynamic.common import config_dir
            view={'trajectory_view':view,'original_evaluation_goal_spec':load_case(run['case_id'])['goal_spec'],
                'annotation_contract':read_json(config_dir()/'annotation.schema.json')}
        prepared=prepare_judge_request(encode_trajectory(view) if pass_name=='trajectory' else view,rubric=prompts[pass_name],
            format_instructions=fmt,output_budget=a.judge_output_budget,representation=VERSION if pass_name=='trajectory' else 'legacy-full',
            judge_binding=config['logical_bindings']['gpt4o'],output_token_parameter=config['logical_bindings']['gpt4o'].get('output_token_parameter') or 'max_tokens')
        write_json(a.out/(pass_name+'-prepared.json'),prepared)
        result=client.send(prepared,request_id='judge_'+uuid.uuid4().hex,pass_name=pass_name,response_ids=ids,evidence_refs=refs)
        annotation['judge_passes'][pass_name]={'prepared':prepared,'result_hash':digest(result),
            'semantic_goals':bool(a.semantic_goals and pass_name=='trajectory'),'synthetic':transport.synthetic}
        write_json(a.out/(pass_name+'-result.json'),result)
        for key,value in result['result'].items():
            if key in annotation and key not in ('response_judgements','trajectory_judgements') and annotation[key]!=value:
                raise DynamicError('judge_pass_conflict',key)
            annotation[key]=value
    # Validate semantic/goal/action references against actual frozen events before offering a scoring input.
    from trustfork.scoring.annotation_contracts import apply_annotations
    from trustfork.scoring.trajectory_observer import analyze_trajectory
    from trustfork.runtime.dynamic.case_loader import load_case
    apply_annotations(analyze_trajectory(events),annotation,events,goal_spec=load_case(run['case_id'])['goal_spec'],evidence_refs=refs,q=run['q'])
    write_json(a.out/'scoring_annotations.json',annotation)
    print(json.dumps({'judge_attempts':transport.count,'synthetic':transport.synthetic,'formal_ready':False,'annotations':'scoring_annotations.json'}))


if __name__=='__main__':main()
