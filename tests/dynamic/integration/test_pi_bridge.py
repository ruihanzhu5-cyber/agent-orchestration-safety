import base64
import json
from pathlib import Path
import pytest
from trustfork.runtime.dynamic.case_loader import load_case
from trustfork.runtime.dynamic.environment import DockerEnvironment
from trustfork.runtime.dynamic.pi_client import PiClient
from trustfork.runtime.dynamic.common import DynamicError


@pytest.fixture
def live(tmp_path):
    env=DockerEnvironment(tmp_path/'task')
    client=None
    try:
        env.prepare(load_case('p001'))
        client=PiClient(tmp_path/'control',env,coordination=lambda actor,name,args,scope:{'status':'queued','sender':actor})
        yield env,client,tmp_path
    finally:
        if client:client.close()
        env.close()


def test_real_sdk_one_turn_full_batch_and_registry(live):
    env,client,_=live
    session,created=client.create_session('C',branch_id='b',task_id='p001',system_prompt='PRIVATE_GOAL_FIXED',
        task_resources=[{'path':'/root/.pi/skills/task/SKILL.md','content':'ORIGINAL_TASK_SKILL'}])
    assert set(('read','bash','edit','write','grep','find','ls'))<=set(created['registry'])
    result=client.call(session,'execute_turn',{'messages':[{'role':'user','content':'work','timestamp':1}],
        'script':{'tools':[{'id':'write1','name':'write','arguments':{'path':'/workspace/pi-real.txt','content':'Pi real Docker\n'}},
                           {'id':'message1','name':'send_message','arguments':{'recipients':['A'],'content':'peer delivery'}}]}},request_id='r1')
    assert result['status']=='success' and result['requests']==1, result['response']
    assert len([e for e in result['events'] if e['type']=='tool_execution_end'])==2
    assert base64.b64decode(env.exec_work_operation('fs.read',{'path':'/workspace/pi-real.txt'},'assert')['data'])==b'Pi real Docker\n'
    assert 'PRIVATE_GOAL_FIXED' in result['actual_input']['systemPrompt']
    assert 'ORIGINAL_TASK_SKILL' in result['actual_input']['systemPrompt']
    second=client.call(session,'execute_turn',{'script':{'text':'done'}},request_id='r2')
    assert second['requests']==1 and second['response']['stopReason']=='stop'
    assert 'PRIVATE_GOAL_FIXED' in second['actual_input']['systemPrompt']
    assert client.call(session,'execute_turn',{'script':{'text':'must not execute'}},request_id='r3')['status']=='idle'
    main,registry=client.create_session('Main',branch_id='b',task_id='p001',system_prompt='Coordinate')
    assert not set(('read','bash','edit','write','grep','find','ls'))&set(registry['registry'])


def test_read_container_and_host_existence_and_missing_no_fallback(live):
    env,client,tmp_path=live
    session,_=client.create_session('D',branch_id='b',task_id='p001',system_prompt='test')
    host=tmp_path/'host-only.txt';host.write_text('NEVER_EXPOSE_HOST_SENTINEL')
    env.exec_work_operation('fs.write',{'path':'/workspace/container-only.txt','data':base64.b64encode(b'CONTAINER_ONLY').decode()},'prepare')
    def read(p,identity):return client.call(session,'probe_tool',{'name':'read','args':{'path':p},'tool_call_id':identity},request_id=identity)
    result=read('/workspace/container-only.txt','container')
    assert result['result']['content'][0]['text']=='CONTAINER_ONLY'
    assert result['guard']['blocked_host_fs']==[]
    for p,identity in [(str(host),'host'),('/workspace/does-not-exist','missing')]:
        with pytest.raises(DynamicError,match='remote_FileNotFoundError'):
            read(p,identity)
    assert host.read_text()=='NEVER_EXPOSE_HOST_SENTINEL'


def test_error_and_aborted_are_not_successful_empty_completions(live):
    _,client,_=live
    for reason in ('error','aborted','stop'):
        session,_=client.create_session('A',branch_id='b',task_id='p001',system_prompt='test')
        result=client.call(session,'execute_turn',{'messages':[{'role':'user','content':'test','timestamp':1}],
            'script':{'text':'','stopReason':reason,'errorMessage':'injected' if reason!='stop' else None}},request_id=reason)
        assert result['status']==('success' if reason=='stop' else 'infra_error')
        assert result['response']['stopReason']==reason
