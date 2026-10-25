"""Real Pi + original Docker environments with local SDK HTTP mocks only."""
import json
import runpy
import threading
import tarfile
from pathlib import Path
from trustfork.agents.pi_dynamic import PiDynamic,ProviderSource
from trustfork.runtime.dynamic.provider import ProviderTransport
from trustfork.runtime.dynamic.common import repo_root,read_json,digest
from trustfork.runtime.dynamic.case_loader import load_case


class MockHistory:
    def __init__(self):self.lock=threading.Lock();self.seen=[]
    def __call__(self,url,body,key,timeout):
        value=json.loads(body)
        messages=value['messages'];system=next((m['content'] for m in messages if m['role'] in ('system','developer')),'')
        packet=json.loads(next(m['content'] for m in reversed(messages) if m['role']=='user'))
        with self.lock:self.seen.append(value)
        if 'planning_contract' in packet:
            text=json.dumps({'plan_status':'delegate','assignments':[{'recipient':a,'task_text':'Mock history work '+a,'context_refs':[]} for a in 'AB'],'draft_answer':None})
            delta={'content':text};finish='stop'
        elif system.startswith('Coordinate'):
            delta={'content':'Mock normal-goal history answer; not a measured task success.'};finish='stop'
        else:
            task=packet.get('work_assignment',{}).get('task_text','')
            actor=task[-1:] if task[-1:] in ('A','B') else 'A'
            target='/workspace/mock-history-'+actor+'-'+digest(packet['public_task'])[:8]+'.txt'
            if not any(m['role']=='tool' and target in json.dumps(m) for m in messages):
                delta={'tool_calls':[{'index':0,'id':'mock-write-'+str(len(self.seen)),'type':'function',
                    'function':{'name':'write','arguments':json.dumps({'path':target,'content':'mock-only history environment marker'})}}]};finish='tool_calls'
            else:delta={'content':'mock work completed'};finish='stop'
        chunks=[{'id':'mock-provider','choices':[{'index':0,'delta':delta,'finish_reason':None}]},
            {'id':'mock-provider','choices':[{'index':0,'delta':{},'finish_reason':finish}],
             'usage':{'prompt_tokens':100,'completion_tokens':20,'total_tokens':120}}]
        return {'status':200,'headers':{'content-type':'text/event-stream','x-request-id':'mock-provider'},
            'body':''.join('data: '+json.dumps(x)+'\n\n' for x in chunks)+'data: [DONE]\n\n'}


def test_mock_h1_h2_execute_original_environments_and_all_stages_without_file_carry(tmp_path,monkeypatch):
    config=runpy.run_path(str(repo_root()/'tests/dynamic/unit/test_provider_preparation.py'))['configuration']()
    import importlib.metadata
    for binding in config['logical_bindings'].values():
        binding['capability']['tokenizer'].update(id='o200k_base',version=importlib.metadata.version('tiktoken'),
            count_method='local-message-content-and-schema-bpe-estimate')
    mock=MockHistory();transport=ProviderTransport(config,mode='mock',journal=tmp_path/'provider-requests.jsonl',http=mock,max_requests=120)
    runtime=PiDynamic('p001',tmp_path/'history-pair',provider=transport,legacy=True,layout='P1')
    history=runtime.run_history(scripts=ProviderSource())
    assert history['synthetic'] is True and history['actual_historical_task_executions']==0
    assert history['mock_environment_task_executions']==2
    assert history['environment_carry'] is False and set(history['actor_states'])=={'Main','A','B'}
    for index,record in enumerate(history['execution_records']):
        case=load_case(record['task_id']);directory=runtime.out/'history'/str(index)
        events=[json.loads(line) for line in (directory/'events.jsonl').read_text().splitlines()]
        assert record['status']=='completed_unjudged'
        assert record['synthetic'] and record['execution_backend']=='mock'
        assert set(record['session_hashes'])=={'Main','A','B'}
        actual_stages={e['stage_id'] for e in events if e['event_type']=='model_request_submitted'}
        assert actual_stages=={s['id'] for s in case['stages']}
        assert any(e['event_type']=='tool_operation_finished' for e in events)
        # Fresh task deployment contains no marker from the preceding task environment.
        with tarfile.open(record['initial_state']['workspace_tar']) as archive:
            assert not any('mock-history-' in name for name in archive.getnames())
        for actor in ('Main','A','B'):
            state=history['actor_states'][actor][index]
            assert state['session']['config']['actor_id']==actor and state['session']['config']['task_id']==record['task_id']
    assert transport.count>0
    rows=[json.loads(line) for line in transport.journal.read_text().splitlines()]
    assert all(r['source']=='mock' for r in rows)
    # Continue the same backend/history into T3. C/D start with no old sessions.
    block=runtime.run_block(ProviderSource(),conditions=['HP'],history=history)
    assert block['branches'][0]['run_status']=='valid_behavior'
    run=runtime.out/'HP/attempt-0/run.json';directory=run.parent
    event_rows=[json.loads(line) for line in (directory/'events.jsonl').read_text().splitlines()]
    for actor in ('C','D'):
        first=next(e for e in event_rows if e['event_type']=='model_request_submitted' and e['actor_id']==actor)
        assert [m['role'] for m in first['payload']['actual_input']['messages']]==['user']
    assert read_json(directory/'run_manifest.json')['history_id']==history['history_id']
    from trustfork.scoring.dynamic_pipeline import score_run
    from trustfork.scoring.scoring_versions import rescore_contract
    from trustfork.scoring.dynamic_adapter import extract_formal_deliverables
    from trustfork.tools.judge_dynamic import main as judge_main
    score_run(run,mode='test-fixtures')
    deliveries=extract_formal_deliverables(event_rows,task_id='p001',allowed_branch_ids={e['branch_id'] for e in event_rows})
    reference=event_rows[0]['branch_id']+'::'+event_rows[0]['event_id']
    values={'response':{'response_judgements':{d['deliverable_id']:{'rtf':0,'rsr':0,'status':'complete',
        'evidence_refs':['response://'+d['deliverable_id']]} for d in deliveries}},
        'trajectory':{'trajectory_judgements':{k:{'value':5 if k in ('terminal_safety','task_utility') else 0,
        'status':'complete','evidence_refs':[reference]} for k in ('ias','saf','vf','ei','terminal_safety','task_utility')}}}
    responses={name:{'status':200,'headers':{'content-type':'application/json'},'body':json.dumps({
        'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value)}}],
        'usage':{'prompt_tokens':50,'completion_tokens':50,'total_tokens':100}})} for name,value in values.items()}
    from trustfork.runtime.dynamic.common import write_json,file_hash
    binding_file=tmp_path/'mock-bindings.json';reply_file=tmp_path/'mock-judge-replies.json';judge_out=tmp_path/'mock-judge-cli'
    write_json(binding_file,config);write_json(reply_file,responses)
    import sys
    monkeypatch.setattr(sys,'argv',['judge_dynamic','--mode','mock','--run',str(run),'--bindings',str(binding_file),
        '--out',str(judge_out),'--judge-output-budget','128','--request-ceiling','2','--mock-responses',str(reply_file)])
    judge_main()
    annotations=read_json(judge_out/'scoring_annotations.json')
    assert annotations['synthetic'] and set(annotations['judge_passes'])=={'response','trajectory'}
    raw_hash=file_hash(run)
    contract=rescore_contract(run,reason='Local mock Judge CLI sidecar integration',annotation_policy='new',new_annotations=judge_out/'scoring_annotations.json')
    score_run(run,mode='test-fixtures',rescore=contract)
    assert file_hash(run)==raw_hash
    assert read_json(directory/'scoring/current_version.json')


def test_mock_invalid_tool_arguments_do_not_execute_and_next_turn_sees_error(tmp_path):
    from trustfork.runtime.dynamic.pi_client import PiClient
    config=runpy.run_path(str(repo_root()/'tests/dynamic/unit/test_provider_preparation.py'))['configuration']()
    calls=[];work=[]
    def http(url,body,key,timeout):
        calls.append(json.loads(body))
        delta=({'tool_calls':[{'index':0,'id':'bad-arguments','type':'function',
            'function':{'name':'write','arguments':'{"path":"/workspace/must-not-write"}'}}]} if len(calls)==1 else {'content':'Handled validation error'})
        return {'status':200,'headers':{'content-type':'text/event-stream'},'body':
            'data: '+json.dumps({'choices':[{'index':0,'delta':delta,'finish_reason':None}]})+'\n\n'+
            'data: '+json.dumps({'choices':[{'index':0,'delta':{},'finish_reason':'tool_calls' if len(calls)==1 else 'stop'}],
                'usage':{'prompt_tokens':20,'completion_tokens':10,'total_tokens':30}})+'\n\ndata: [DONE]\n\n'}
    class NeverWork:
        def exec_work_operation(self,*args,**kwargs):
            work.append(args)
            from trustfork.runtime.dynamic.common import DynamicError
            raise DynamicError('unexpected_remote_work','Invalid tool args must be rejected before execution')
    transport=ProviderTransport(config,mode='mock',journal=tmp_path/'provider-requests.jsonl',http=http,max_requests=2)
    client=PiClient(tmp_path/'control',NeverWork(),provider=transport,model_refs={'A':'gpt4o'})
    try:
        session,_=client.create_session('A',branch_id='mock-invalid-tool',task_id='p001',system_prompt='Mock agent')
        first=client.call(session,'execute_turn',{'messages':[{'role':'user','content':'local mock work','timestamp':1}]},request_id='invalid-args')
        assert any(e['type']=='tool_execution_end' and e.get('isError') for e in first['events'])
        second=client.call(session,'execute_turn',{},request_id='resume-after-error')
        assert second['response']['stopReason']=='stop'
        assert any(m['role']=='tool' for m in calls[1]['messages'])
        assert work==[] and transport.count==2
    finally:client.close()
