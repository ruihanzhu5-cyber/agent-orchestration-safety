import json
import pytest
from trustfork.agents.pi_dynamic import PiDynamic,ScriptSource
from trustfork.runtime.dynamic.pi_client import PiClient
from trustfork.runtime.dynamic.budget import Budget
from trustfork.runtime.dynamic.scripted_fixtures import branch_scripts


def message(text):return {'role':'user','content':text,'timestamp':1}


def test_real_pi_empty_restore_compaction_reload_and_private_goal(tmp_path):
    client=PiClient(tmp_path/'control',None)
    resource={'path':'/workspace/.pi/skills/original/SKILL.md','content':'---\nname: original-fixture\ndescription: Original resource fixture.\n---\nOriginal lazy body.','kind':'skill'}
    try:
        first,_=client.create_session('C',branch_id='b',task_id='fixture',system_prompt='PRIVATE_GOAL',task_resources=[resource])
        empty=client.call(first,'export_session');assert empty['empty']
        assert not any(e['type']=='message' and e['message']['role']=='assistant' for e in empty['entries'])
        restored,_=client.create_session('C',branch_id='b2',task_id='fixture',system_prompt='PRIVATE_GOAL',task_resources=[resource],snapshot=empty)
        assert client.call(restored,'execute_turn',{'script':{'text':'unused'}},request_id='idle')['status']=='idle'
        result=client.call(restored,'execute_turn',{'messages':[message('context')],'script':{'text':'first'}},request_id='one')
        assert result['status']=='success' and 'PRIVATE_GOAL' in result['actual_input']['systemPrompt']
        assert 'Original resource fixture.' in result['actual_input']['systemPrompt']
        saved=client.call(restored,'export_session');assert saved['entries'] and not saved['empty']
        client.call(restored,'reload_resources',{'system_prompt':'PRIVATE_GOAL','task_resources':[resource]})
        budget=Budget();reservation=budget.reserve('maintenance',0,maintenance=True,actor_id='Main')
        entry=next(x for x in saved['entries'] if x['type']=='message')
        client.call(restored,'maintenance_compact_fixture',{'summary':'Synthetic supplied summary of the earlier context.',
            'first_kept_entry_id':entry['id'],'tokens_before':1},request_id=reservation['attempt_id'])
        budget.finish(reservation['attempt_id'],output_tokens=6,status='synthetic_maintenance',cost=0)
        result=client.call(restored,'execute_turn',{'messages':[message('after maintenance')],'script':{'text':'second'}},request_id='two')
        assert 'PRIVATE_GOAL' in result['actual_input']['systemPrompt']
        assert 'Original resource fixture.' in result['actual_input']['systemPrompt']
        assert budget.attempts[0]['maintenance'] and budget.output_tokens==6
        snapshot=client.call(restored,'export_session')
        after,_=client.create_session('C',branch_id='b3',task_id='fixture',system_prompt='PRIVATE_GOAL',task_resources=[resource],snapshot=snapshot)
        assert client.call(after,'execute_turn',{'script':{'text':'unused'}},request_id='completed-idle')['status']=='idle'
        result=client.call(after,'execute_turn',{'messages':[message('third')],'script':{'text':'third'}},request_id='three')
        assert 'PRIVATE_GOAL' in result['actual_input']['systemPrompt'] and result['guard']['network_attempts']==0
    finally:client.close()


def test_host_transport_retry_uses_real_pi_and_restores_prior_chat(tmp_path):
    engine=PiDynamic('p001',tmp_path/'run')
    engine._initialize(tmp_path/'control','fixture-branch')
    engine.resources=[];engine._create_actor('Main')
    engine.current_scripts=ScriptSource({'planning:0:Main':[
        {'transportFailure':'http_429','outputTokens':0},
        {'transportFailure':'disconnect_before_generation','outputTokens':0},
        {'text':json.dumps({'plan_status':'refusal','assignments':[],'draft_answer':'Refusal.'})}]})
    try:
        result=engine._turn('Main','planning')
        assert result['status']=='success' and len(engine.budget.attempts)==3
        assert [a['status'] for a in engine.budget.attempts]==['transport_error','transport_error','success']
        # Retried inputs are identical except runtime timestamp metadata; error
        # assistants from the failed attempts never enter the successful input.
        assert len([m for m in result['actual_input']['messages'] if m['role']=='user'])==1
        assert not any(m['role']=='assistant' for m in result['actual_input']['messages'])
        assert result['guard']['network_attempts']==0
        before_startup=json.loads(json.dumps(engine.scheduler.startup))
        saved=engine.client.call(engine.sessions['Main'],'export_session')
        entry=next(x for x in saved['entries'] if x['type']=='message')
        engine.maintain_compaction_fixture('Main',summary='Explicit synthetic maintenance summary.',
            first_kept_entry_id=entry['id'],tokens_before=1,output_tokens=6)
        assert len(engine.budget.attempts)==4 and engine.budget.attempts[-1]['maintenance']
        assert engine.scheduler.startup==before_startup
    finally:engine.client.close();engine.environment.close()
