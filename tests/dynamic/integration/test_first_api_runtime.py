"""Real locked Pi + Docker; every provider response is mock/scripted, never external."""
import base64,json,runpy
from collections import deque
import pytest
from trustfork.runtime.dynamic.common import repo_root,digest,DynamicError
from trustfork.runtime.dynamic.environment import DockerEnvironment
from trustfork.runtime.dynamic.case_loader import load_case
from trustfork.runtime.dynamic.provider import ProviderTransport
from trustfork.runtime.dynamic.pi_client import PiClient
from trustfork.agents.pi_dynamic import PiDynamic,ProviderSource,ScriptSource
from trustfork.runtime.dynamic.scripted_fixtures import branch_scripts,history_scripts

def config():
 return runpy.run_path(str(repo_root()/'tests/dynamic/unit/test_provider_preparation.py'))['configuration']()

def sse(delta,finish='stop'):
 chunks=[{'choices':[{'index':0,'delta':delta,'finish_reason':None}]},
  {'choices':[{'index':0,'delta':{},'finish_reason':finish}],'usage':{'prompt_tokens':100,'completion_tokens':5,'total_tokens':105,'completion_tokens_details':{'reasoning_tokens':3}}}]
 return {'status':200,'headers':{'content-type':'text/event-stream'},'body':''.join('data: '+json.dumps(x)+'\n\n' for x in chunks)+'data: [DONE]\n\n'}

def test_high_thinking_real_session_export_restore_tool_and_private_replay(tmp_path):
 c=config();b=c['logical_bindings']['deepseekflash'];b.update(provider='deepseek',model_id='exact-deepseek',thinking='enabled',reasoning_effort='high',supported_parameters=['max_tokens','thinking','reasoning_effort'])
 b['compat'].update(supportsReasoningEffort=True,requiresReasoningContentOnAssistantMessages=True)
 route=digest({k:b[k] for k in ('provider','base_url','model_id')});b['capability']['route_fingerprint']=route;b['capability']['tokenizer']['applicable_route']=route
 replies=deque([sse({'reasoning_content':'FIRST_PRIVATE','content':'ordinary first answer'}),
  sse({'reasoning_content':'SECOND_PRIVATE','tool_calls':[{'index':0,'id':'write-effect','type':'function','function':{'name':'write','arguments':json.dumps({'path':'/workspace/thinking-effect.txt','content':'42'})}}]},'tool_calls'),
  sse({'reasoning_content':'THIRD_PRIVATE','content':'done'})])
 sent=[]
 def http(url,body,key,timeout):sent.append(json.loads(body));return replies.popleft()
 transport=ProviderTransport(c,mode='mock',journal=tmp_path/'requests.jsonl',http=http,max_requests=3)
 env=DockerEnvironment(tmp_path/'task');client=None
 try:
  env.prepare(load_case('p001'));client=PiClient(tmp_path/'control',env,provider=transport,model_refs={'A':'deepseekflash','B':'deepseekflash'})
  session,_=client.create_session('A',branch_id='b',task_id='p001',system_prompt='Normal test task')
  first=client.call(session,'execute_turn',{'messages':[{'role':'user','content':'first','timestamp':1}],'max_output_tokens':100},request_id='first')
  assert first['status']=='success' and any(x['type']=='thinking' and x['thinking']=='FIRST_PRIVATE' for x in first['response']['content'])
  state=client.call(session,'export_session');client.call(session,'close')
  restored,_=client.create_session('A',branch_id='b',task_id='p001',system_prompt='Normal test task',snapshot=state)
  second=client.call(restored,'execute_turn',{'messages':[{'role':'user','content':'write','timestamp':2}],'max_output_tokens':100},request_id='second')
  assert second['status']=='success' and second['response']['stopReason']=='toolUse'
  assert base64.b64decode(env.exec_work_operation('fs.read',{'path':'/workspace/thinking-effect.txt'},'assert-effect')['data'])==b'42'
  state2=client.call(restored,'export_session');client.call(restored,'close')
  restored2,_=client.create_session('A',branch_id='b',task_id='p001',system_prompt='Normal test task',snapshot=state2)
  third=client.call(restored2,'execute_turn',{'messages':[{'role':'user','content':'after restore','timestamp':3}],'max_output_tokens':100},request_id='third')
  assert third['status']=='success'
  assert all(p['thinking']=={'type':'enabled'} and p['reasoning_effort']=='high' and 'temperature' not in p for p in sent)
  assert [m['reasoning_content'] for m in sent[2]['messages'] if m['role']=='assistant']==['FIRST_PRIVATE','SECOND_PRIVATE']
  other,_=client.create_session('B',branch_id='b',task_id='p001',system_prompt='Independent actor')
  assert 'FIRST_PRIVATE' not in json.dumps(client.call(other,'export_session'))
 finally:
  if client:client.close()
  env.close()

def test_malformed_complete_looking_tool_json_has_no_docker_effect(tmp_path):
 c=config()
 reply=sse({'tool_calls':[{'index':0,'id':'half','type':'function','function':{'name':'write','arguments':'{"path":"/workspace/should-not-exist","content":"BAD"'}}]},'tool_calls')
 transport=ProviderTransport(c,mode='mock',journal=tmp_path/'requests.jsonl',http=lambda *a:reply,max_requests=1)
 env=DockerEnvironment(tmp_path/'task');client=None
 try:
  env.prepare(load_case('p001'));client=PiClient(tmp_path/'control',env,provider=transport,model_refs={'A':'gpt4o'})
  session,_=client.create_session('A',branch_id='b',task_id='p001',system_prompt='Offline invalid JSON test')
  result=client.call(session,'execute_turn',{'messages':[{'role':'user','content':'write','timestamp':1}],'max_output_tokens':100},request_id='half')
  assert result['status']=='infra_error' and result['error']['code']=='provider_tool_json_incomplete'
  assert not any(e['type']=='tool_execution_start' for e in result['events'])
  assert env.exec_work_operation('fs.exists',{'path':'/workspace/should-not-exist'},'assert-none')['exists'] is False
 finally:
  if client:client.close()
  env.close()

def test_capacity_error_crosses_bridge_and_does_not_confirm_mailbox(tmp_path):
 c=config();c['execution_scope']='engineering_smoke'
 for b in c['logical_bindings'].values():b['capability']['status']='declared'
 c['logical_bindings']['gpt4o']['capability']['effective_context_tokens']=100
 c['logical_bindings']['gpt4o']['max_output_tokens']=8192
 c['execution_limits']={k:{'max_cost_usd':10,'requests_per_minute':100,'tokens_per_minute':1000000,'prices_per_million':{'exact-fixture':{'input':1,'output':2}}} for k in ('model','judge')}
 c['campaign_budget']={'path':str(tmp_path/'cost.sqlite'),'campaign_id':'first-api-20261026','phase':'interface_probe',
  'pricing_basis':'mock-only fixture','conversion_basis':'mock-only conversion','usd_to_cny_upper_bound':8,'account_price_upper_bound_confirmed':True}
 t=ProviderTransport(c,mode='mock',journal=tmp_path/'requests.jsonl',http=lambda *a:pytest.fail('No send after capacity rejection'),max_requests=2)
 r=PiDynamic('p001',tmp_path/'runtime',provider=t)
 r._initialize(r.out,'branch-capacity');r.current_scripts=ProviderSource()
 try:
  r.environment.prepare(r.case);r.resources=r._resources();r._create_actor('A')
  r.mailbox.enqueue('B',['A'],'FULL_PEER_MESSAGE',branch_id=r.ledger.branch_id,epoch=0)
  with pytest.raises(DynamicError,match='provider_capacity_blocked'):r._turn('A','running')
  assert r.mailbox.messages[0]['delivery']['A']['status']=='queued'
  assert not any(e['event_type']=='message_exposed' for e in r.ledger.rows)
  assert t.count==0 and r.budget.output_tokens==0
 finally:r.client.close();r.environment.close()

def test_sub_length_retains_executed_effect_peer_and_partial_delivery(tmp_path):
 r=PiDynamic('p001',tmp_path/'runtime')
 r.run_history(scripts=ScriptSource(history_scripts()))
 scripts=branch_scripts('p001',peer=True)
 scripts['running:0:C']=[{'tools':[
  {'id':'effect','name':'write','arguments':{'path':'/workspace/budget-effect.txt','content':'PRESERVED_EFFECT'}},
  {'id':'peer','name':'send_message','arguments':{'recipients':['B'],'content':'PRESERVED_PEER'}}]},
  {'text':'partial answer','stopReason':'length'}]
 block=r.run_block(ScriptSource(scripts),conditions=['HA'])
 run=block['branches'][0];events=r.ledger.rows
 assert any(e['event_type']=='model_response' and e['actor_id']=='C' and e['payload']['completion_status']=='partial' for e in events)
 assert any(d['actor_id']=='C' and d['result_status']=='partial' for d in run['formal_deliverables'])
 assert not any(x['actor_id']=='C' and x['status'] in ('started','released') for x in r.delegations.rows)
 assert any(e['event_type']=='message_enqueued' and e['payload']['content']=='PRESERVED_PEER' for e in events)
 from trustfork.scoring.goal_observer import frozen_workspace
 assert base64.b64decode(frozen_workspace(run['frozen_export'])['paths']['/workspace/budget-effect.txt']['content_b64'])==b'PRESERVED_EFFECT'
 from trustfork.scoring.dynamic_pipeline import score_run
 summary=score_run(r.directory/'run.json',mode='test-fixtures')
 assert summary['observation_complete'] is False
