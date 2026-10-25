"""Fault and input-boundary tests with actual Pi/Docker and explicit fixtures."""
import base64
import concurrent.futures
import json
import time
from pathlib import Path
import pytest
from trustfork.agents.pi_dynamic import PiDynamic,ScriptSource
from trustfork.runtime.dynamic.case_loader import load_case
from trustfork.runtime.dynamic.common import DynamicError,read_json,repo_root
from trustfork.runtime.dynamic.environment import DockerEnvironment
from trustfork.runtime.dynamic.pi_client import PiClient
from trustfork.runtime.dynamic.scripted_fixtures import branch_scripts
from trustfork.scoring.dynamic_pipeline import score_run


def wait_for(predicate,seconds=10):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        if predicate():return
        time.sleep(.02)
    pytest.fail('Required observable event did not arrive before the test deadline')


@pytest.mark.parametrize('arrival',['generation','tool'])
def test_message_after_fixed_input_enters_next_real_request_only(tmp_path,arrival):
    engine=PiDynamic('p001',tmp_path/'engine');engine._initialize(tmp_path/'engine','timing-fixture')
    try:
        engine.environment.prepare(engine.case);engine.resources=engine._resources()
        engine.lifecycle.transition('PLAN_READY');engine.lifecycle.transition('JOINING')
        engine.membership.admit_atomic(['C','D']);engine.lifecycle.transition('COORDINATING');engine.lifecycle.transition('RUNNING')
        for actor in ('A','B'):engine._create_actor(actor)
        first={'text':'first response','delayMs':1200} if arrival=='generation' else {'tools':[{'id':'slow-bash','name':'bash','arguments':{'command':'sleep 1; printf task-finished'}}]}
        engine.current_scripts=ScriptSource({'running:0:A':[first,{'text':'second response'}],
            'running:0:B':[{'tools':[{'id':'actual-peer','name':'send_message','arguments':{'recipients':['A'],'content':'真实 peer 消息，下一轮可见。'}}]}]})
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            future=pool.submit(engine._turn,'A','running')
            event='model_request_submitted' if arrival=='generation' else 'tool_operation_started'
            wait_for(lambda:any(e['event_type']==event and e['actor_id']=='A' for e in engine.ledger.rows))
            other=pool.submit(engine._turn,'B','running');other.result(timeout=20)
            first_result=future.result(timeout=20)
        assert engine._actual_packet(first_result['actual_input'])['peer_messages']==[]
        assert not any(e['event_type']=='message_exposed' and e['actor_id']=='A' for e in engine.ledger.rows)
        second=engine._turn('A','running')
        peers=engine._actual_packet(second['actual_input'])['peer_messages']
        assert len(peers)==1 and peers[0]['content']=='真实 peer 消息，下一轮可见。'
        assert len([e for e in engine.ledger.rows if e['event_type']=='message_exposed' and e['actor_id']=='A'])==1
        assert second['guard']['network_attempts']==0
    finally:engine.client.close();engine.environment.close()


def test_actual_cancel_kills_task_process_and_never_runs_late_write(tmp_path):
    environment=DockerEnvironment(tmp_path/'task');client=None
    try:
        environment.prepare(load_case('p001'));client=PiClient(tmp_path/'control',environment)
        session,_=client.create_session('A',branch_id='b',task_id='p001',system_prompt='Fixture')
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(client.call,session,'execute_turn',{'messages':[{'role':'user','content':'fixture','timestamp':1}],
                'script':{'tools':[{'id':'cancel-bash','name':'bash','arguments':{'command':'echo $$ > /workspace/cancel.pid; sleep 20; printf late > /workspace/should-not-exist'}}]}},request_id='cancel-turn')
            wait_for(lambda:bool(environment.active))
            wait_for(lambda:environment._worker('fs.exists',{'path':'/workspace/cancel.pid'},'pid-ready')['exists'])
            pid=int(base64.b64decode(environment._worker('fs.read',{'path':'/workspace/cancel.pid'},'pid-read')['data']))
            client.call(session,'cancel',request_id='cancel-command')
            result=future.result(timeout=12)
        assert result['status']=='infra_error' and result['termination_status']=='cancelled'
        assert not environment._worker('fs.exists',{'path':'/workspace/should-not-exist'},'late-check')['exists']
        assert all(row['pid']!=pid for row in environment._worker('process.snapshot',{},'cancel-state')['processes'])
        assert result['guard']['blocked_host_exec']==[] and result['guard']['network_attempts']==0
    finally:
        if client:client.close()
        environment.close()


def test_real_pi_unfinished_work_continues_beyond_four_request_startup_slice(tmp_path):
    engine=PiDynamic('p001',tmp_path/'slices');engine._initialize(tmp_path/'slices','slice-fixture')
    try:
        engine.environment.prepare(engine.case);engine.resources=engine._resources()
        engine.lifecycle.transition('PLAN_READY');engine.lifecycle.transition('JOINING')
        engine.membership.admit_atomic(['C','D']);engine.lifecycle.transition('COORDINATING');engine.lifecycle.transition('RUNNING')
        engine._create_actor('C')
        startup=engine.delegations.prepare('C',engine._stage()['user_request'],source='runtime_startup',
            epoch=engine.lifecycle.epoch,stage_id=engine.lifecycle.stage_id)
        engine.scheduler.begin_startup(['C']);engine.scheduler.bind_startup(startup);engine._release()
        engine.current_scripts=ScriptSource({'running:0:C':[{'tools':[{'id':f'list-{i}','name':'ls','arguments':{'path':'/workspace'}}]} for i in range(5)]+[{'text':'finished after five tool turns'}]})
        results=[]
        for index in range(6):
            permit=engine.scheduler.permit();assert permit['actor_id']=='C'
            result=engine._turn('C','running',engine._next_invocation('C'));results.append(result)
            engine.scheduler.complete('C',unfinished=result['response']['stopReason']=='toolUse')
            if index==3:
                assert engine.scheduler.startup['C']['requests']==4
                assert engine.scheduler.startup['C']['status']=='four_request_limit'
                assert engine.scheduler.startup['C']['invocation_id']==startup['invocation_id']
        assert len(results)==6 and all(result['requests']==1 and result['status']=='success' for result in results)
        assert not engine.scheduler.queue and engine.scheduler.startup['C']['requests']==4
        assert engine.delegations.rows[0]['status']=='terminal'
        assert all(not record['recipient_ids'] for record in engine.formal_deliverables.values())
        assert len(engine.budget.attempts)==6 and all(result['guard']['network_attempts']==0 for result in results)
        closed=[event for event in engine.ledger.rows if event['event_type']=='startup_slice_closed']
        assert len(closed)==1 and closed[0]['payload']['message_status']=='no_message_at_slice_end'
    finally:engine.client.close();engine.environment.close()


def test_original_skill_is_lazy_then_read_inside_original_task(tmp_path):
    environment=DockerEnvironment(tmp_path/'task');client=None
    try:
        case=load_case('p006');environment.prepare(case)
        resources=environment._worker('resource.snapshot',{},'resources')['resources']
        skill_paths=[row['path'] for row in case['deployed_assets'] if row['type']=='file' and row['path'].endswith('/SKILL.md')]
        assert skill_paths==['workspace/skills/auto-updater/SKILL.md']
        selected={'path':'/workspace/skills/auto-updater/SKILL.md'}
        # The fixed task has no skills setting/registration. The unchanged Pi
        # default discovery likewise returns no automatic skills. The original
        # workspace skill remains discoverable and readable by the seven tools.
        assert not [resource for resource in resources if resource['kind']=='skill']
        client=PiClient(tmp_path/'control',environment)
        session,_=client.create_session('C',branch_id='b',task_id='p006',system_prompt='Private goal fixture',task_resources=resources)
        result=client.call(session,'execute_turn',{'messages':[{'role':'user','content':'Read original skill','timestamp':1}],
            'script':{'tools':[{'id':'original-skill-read','name':'read','arguments':{'path':selected['path']}}]}},request_id='skill')
        assert result['status']=='success'
        expected=base64.b64decode(environment._worker('fs.read',{'path':selected['path']},'skill-bytes')['data']).decode()
        ends=[e for e in result['events'] if e['type']=='tool_execution_end'];assert len(ends)==1 and not ends[0]['isError']
        assert expected.strip() in ends[0]['result']['content'][0]['text']
        saved=client.call(session,'export_session')
        restored,_=client.create_session('C',branch_id='restored',task_id='p006',system_prompt='Private goal fixture',task_resources=resources,snapshot=saved)
        next_result=client.call(restored,'execute_turn',{'script':{'text':'Skill read fixture completed.'}},request_id='after-tool-restore')
        assert next_result['status']=='success'
        actual_tool_results=[part['text'] for message in next_result['actual_input']['messages'] if message['role']=='toolResult'
            for part in message['content'] if part['type']=='text']
        assert any(expected.strip() in text for text in actual_tool_results)
        assert 'Private goal fixture' in next_result['actual_input']['systemPrompt']
    finally:
        if client:client.close()
        environment.close()


def test_original_chain_retains_then_resets_chat_and_pending_messages(tmp_path):
    class RaceFixture(PiDynamic):
        def _stage_reset(self,epoch,new_session):
            self.mailbox.enqueue('A',['B'],f'explicit boundary race fixture {epoch}',branch_id=self.ledger.branch_id,epoch=epoch)
            self.ledger.append('synthetic_boundary_injection',{'epoch':epoch,'new_session':new_session})
            super()._stage_reset(epoch,new_session)
    engine=RaceFixture('p024',tmp_path/'chain')
    scripts=branch_scripts('p024')
    scripts['running:0:A']=[{'text':'UNIQUE_STAGE_ZERO_A_CHAT'}]
    result=engine.run_block(ScriptSource(scripts),conditions=('HP',))
    assert result['branches'][0]['run_status']=='valid_behavior'
    stages=load_case('p024')['stages'];assert len(stages)==3 and not stages[1]['new_session'] and stages[2]['new_session']
    events=[json.loads(line) for line in (tmp_path/'chain/HP/attempt-0/events.jsonl').read_text().splitlines()]
    requests=[e for e in events if e['event_type']=='model_request_submitted']
    a1=next(e for e in requests if e['actor_id']=='A' and e['stage_epoch']==1)
    a2=next(e for e in requests if e['actor_id']=='A' and e['stage_epoch']==2)
    assert 'UNIQUE_STAGE_ZERO_A_CHAT' in json.dumps(a1['payload']['actual_input']['messages'])
    assert 'UNIQUE_STAGE_ZERO_A_CHAT' not in json.dumps(a2['payload']['actual_input']['messages'])
    b1=[e for e in requests if e['actor_id']=='B' and e['stage_epoch']==1]
    assert any('explicit boundary race fixture 0' in json.dumps(e['payload']['actual_input']['messages']) for e in b1)
    b2=[e for e in requests if e['actor_id']=='B' and e['stage_epoch']==2]
    assert all('explicit boundary race fixture' not in json.dumps(e['payload']['actual_input']['messages']) for e in b2)
    receipts=read_json(tmp_path/'chain/HP/attempt-0/delivery_receipts.json')
    first=next(m for m in receipts['messages'] if m['content']=='explicit boundary race fixture 0')
    last=next(m for m in receipts['messages'] if m['content']=='explicit boundary race fixture 1')
    assert first['carried_from_epoch']==0 and first['delivery']['B']['status']=='confirmed_exposure'
    assert last['delivery']['B']['status']=='cancelled_new_session'


@pytest.mark.parametrize('case_id,protocol',[('p001','S'),('p028','L')])
def test_actual_risk_object_observed_without_main_adoption_and_prejoin_attribution(tmp_path,case_id,protocol):
    case=load_case(case_id);target=(repo_root()/case['source_task_path']/'environment/workspace/contact.md').read_text()
    harmed=target.replace('18600998877','1994278666');assert harmed!=target
    scripts=branch_scripts(case_id,protocol=protocol)
    engine=PiDynamic(case_id,tmp_path/case_id,protocol=protocol)
    if protocol=='S':
        scripts['running:0:C']=[{'tools':[{'id':'direct-goal-write','name':'write','arguments':{'path':'/workspace/contact.md','content':harmed}}]},
            {'tools':[{'id':'restore-contact','name':'write','arguments':{'path':'/workspace/contact.md','content':target}}]},
            {'text':'Synthetic direct-state observer fixture finished.'}]
    else:
        scripts['late_prefix:0:A']=[{'tools':[{'id':'old-member-harm','name':'write','arguments':{'path':'/workspace/contact.md','content':harmed}}]},
            {'text':'Synthetic old member progress.'}]
        scripts['running:0:D']=[{'tools':[{'id':'original-memory-read','name':'read','arguments':{'path':'/workspace/MEMORY.md'}}]},
            {'text':'Synthetic memory context read completed.'}]
    result=engine.run_block(ScriptSource(scripts),conditions=('HA',))
    assert result['branches'][0]['run_status']=='valid_behavior'
    summary=score_run(tmp_path/case_id/'HA/attempt-0/run.json',mode='test-fixtures')
    goal=summary['goal_observations']
    assert goal['goal_observed_achieved']['value'] is True
    if protocol=='S':
        assert goal['prejoin_goal_state']['value'] is False and goal['goal_terminal_achieved']['value'] is False
        assert goal['postjoin_new_effect_observed']['value'] is True
        observation=read_json(tmp_path/case_id/'HA/attempt-0/scoring/trajectory_observations.json')['data']
        assert observation['recovery_observation']['status']=='recovered'
    else:
        assert goal['prejoin_goal_state']['value'] is True and goal['goal_terminal_achieved']['value'] is True
        assert goal['prejoin_harm_excluded_from_q_attribution'] and not goal['postjoin_new_effect_observed']['value']
        events=[json.loads(line) for line in (tmp_path/case_id/'HA/attempt-0/events.jsonl').read_text().splitlines()]
        memory=(repo_root()/case['source_task_path']/'environment/workspace/MEMORY.md').read_text().strip()
        requests=[event for event in events if event['event_type']=='model_request_submitted' and event['actor_id']=='D']
        assert any(memory in part['text'] for event in requests for message in event['payload']['actual_input']['messages']
            if message['role']=='toolResult' for part in message['content'] if part['type']=='text')
    assert summary['synthetic'] and summary['real_model_requests']==summary['real_judge_requests']==0
