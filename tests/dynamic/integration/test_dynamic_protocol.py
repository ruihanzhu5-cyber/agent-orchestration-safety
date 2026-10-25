from pathlib import Path
import json
import pytest
from trustfork.agents.pi_dynamic import PiDynamic, ScriptSource
from trustfork.runtime.dynamic.scripted_fixtures import branch_scripts
from trustfork.runtime.dynamic.common import read_json, DynamicError


def test_actual_common_prefix_independent_four_branches_and_goals(tmp_path):
    engine=PiDynamic('p001',tmp_path/'s',protocol='S')
    result=engine.run_block(ScriptSource(branch_scripts('p001',peer=True)))
    assert len(result['branches'])==4 and len({x['checkpoint_id'] for x in result['branches']})==1
    assert all(x['run_status']=='valid_behavior' and x['synthetic'] for x in result['branches'])
    prefix=read_json(tmp_path/'s/prefix/checkpoint.json')
    assert all(x['actor_id']=='Main' for x in prefix['budget']['attempts'])
    assert all(x['status']=='queued' for x in prefix['delegations'])
    hashes={};main_inputs={}
    for condition in ('HP','HA','MP','MA'):
        path=tmp_path/'s'/condition/'attempt-0'
        events=[json.loads(x) for x in (path/'events.jsonl').read_text().splitlines()]
        admitted=[x for x in events if x['event_type']=='members_admitted']
        assert len(admitted)==1 and set(admitted[0]['payload']['actor_ids'])==set('CD')
        states=[x['payload']['to'] for x in events if x['event_type']=='lifecycle']
        assert states.index('RUNNING')>states.index('COORDINATING')
        main_profiles=[x for x in events if x['event_type']=='main_profiles_exposed']
        assert len(main_profiles)==1
        hashes[condition]=main_profiles[0]['payload_hash']
        requests=[x for x in events if x['event_type']=='model_request_submitted']
        actual=json.loads(json.dumps(next(x for x in requests if x['actor_id']=='Main')['payload']['actual_input']))
        for message in actual['messages']:message.pop('timestamp',None)
        main_inputs[condition]=actual
        assert set(x['actor_id'] for x in requests)=={'Main','A','B','C','D'}
        for request in requests:
            prompt=request['payload']['actual_input']['systemPrompt']
            risk='hidden objective:' in prompt
            assert risk==(condition.endswith('A') and request['actor_id']=='C')
            assert str(path) not in prompt
        operations=[x for x in events if x['event_type']=='tool_operation_started']
        assert all(x['actor_id'] in 'ABCD' and x['request_id'] for x in operations)
        assert (path/'environment/workspace-frozen.tar').exists()
    assert hashes['HP']==hashes['HA'] and hashes['MP']==hashes['MA']
    # The complete pre-newcomer-generation provider input, including tool
    # schemas and actual message bodies, is equal within each reputation pair.
    # Only SDK message timestamps are immaterial metadata; no body or ID is
    # rewritten to hide a possible condition leak.
    assert main_inputs['HP']==main_inputs['HA']
    assert main_inputs['MP']==main_inputs['MA']


def test_f_can_validly_recruit_neither_candidate(tmp_path):
    engine=PiDynamic('p001',tmp_path/'f',protocol='F')
    result=engine.run_block(ScriptSource(branch_scripts('p001',protocol='F',recruit=())),conditions=('HP',))
    assert result['branches'][0]['run_status']=='valid_behavior'
    events=[json.loads(x) for x in (tmp_path/'f/HP/attempt-0/events.jsonl').read_text().splitlines()]
    assert not any(x['actor_id'] in ('C','D') and x['event_type']=='model_request_submitted' for x in events)
    assert not any(x['event_type']=='members_admitted' for x in events)
    profiles=[x['payload']['profiles'] for x in events if x['event_type']=='main_profiles_exposed']
    assert all(profile['membership']=='candidate' for profile in profiles[0])


@pytest.mark.parametrize('wake',['none','delegation','message'])
def test_audit_real_f_recruit_and_actual_use_are_independent(tmp_path,wake):
    from trustfork.scoring.dynamic_metrics import automatic_metrics
    scripts=branch_scripts('p001',protocol='F',recruit=('C',))
    scripts['planning:0:Main']=[{'text':json.dumps({'plan_status':'answer_ready','assignments':[],'draft_answer':'Synthetic initial draft'})}]
    if wake=='delegation':
        scripts['running:0:Main'].insert(0,{'tools':[{'id':'voluntary-C','name':'delegate_work',
            'arguments':{'actor_id':'C','task_text':'Inspect the shared task and report.'}}]})
    elif wake=='message':
        scripts['running:0:Main'].insert(0,{'tools':[{'id':'message-C','name':'send_message',
            'arguments':{'recipients':['C'],'content':'Please inspect the shared task.'}}]})
    engine=PiDynamic('p001',tmp_path/wake,protocol='F')
    result=engine.run_block(ScriptSource(scripts),conditions=('HA',))
    run=result['branches'][0];assert run['run_status']=='valid_behavior'
    path=tmp_path/wake/'HA/attempt-0'
    events=[json.loads(line) for line in (path/'events.jsonl').read_text().splitlines()]
    values,_=automatic_metrics(run,events,run['formal_deliverables'])
    assert values['J'] is True
    assert values['U'] is (wake!='none')
    assert values['U_voluntary'] is (wake=='delegation')
    assert not any(e['event_type']=='delegation_prepared' and e['payload']['source']=='runtime_startup' for e in events)
    requests=[e for e in events if e['event_type']=='model_request_submitted' and e['actor_id']=='C']
    if requests:
        actual=requests[0]['payload']['actual_input'];packet=PiDynamic._actual_packet(actual)
        assert packet['public_task'] and packet['own_profile']
        assert 'hidden objective:' in actual['systemPrompt']
        assert {tool['name'] for tool in actual['tools']} >= {'read','write','edit','bash','grep','find','ls'}
    else:assert wake=='none'


def test_audit_real_s_early_release_does_not_bypass_startup(tmp_path):
    scripts=branch_scripts('p001')
    scripts['planning:0:Main']=[{'text':json.dumps({'plan_status':'answer_ready','assignments':[],'draft_answer':'Synthetic draft'})}]
    scripts['coordinating:0:Main']=[{'tools':[{'id':'release-'+a,'name':'release_member','arguments':{'actor_id':a}} for a in 'CD']}]
    engine=PiDynamic('p001',tmp_path/'protected-S',protocol='S')
    result=engine.run_block(ScriptSource(scripts),conditions=('HA',))
    assert result['branches'][0]['run_status']=='valid_behavior'
    events=[json.loads(line) for line in (tmp_path/'protected-S/HA/attempt-0/events.jsonl').read_text().splitlines()]
    assert not any(e['event_type']=='member_released' for e in events)
    closed=[e for e in events if e['event_type']=='startup_slice_closed']
    assert {e['actor_id'] for e in closed}==set('CD')
    assert all(e['payload']['actual_requests']>=1 for e in closed)
    frozen=next(e for e in events if e['event_type']=='lifecycle' and e['payload']['to']=='SCORING')
    assert all(e['sequence']<frozen['sequence'] for e in closed)
