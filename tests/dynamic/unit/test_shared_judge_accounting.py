import copy,json
import pytest
from trustfork.runtime.dynamic.common import DynamicError,digest
from trustfork.runtime.dynamic.token_accounting import count_request,route_counting_policy
from trustfork.runtime.dynamic.provider import ProviderTransport
from trustfork.runtime.dynamic.schema import validate_bindings
from trustfork.runtime.dynamic.experiment_config import resolve_experiment
from trustfork.scoring.judge_request import build_judge_bundle,prepare_judge_pass
from trustfork.scoring.dynamic_adapter import trajectory_judge_view
from trustfork.scoring.trajectory_codec import decode_trajectory
from test_provider_preparation import configuration

def policy():return {'counter':len,'framing_tokens':None,'route_fingerprint':'fixture','status':'fixture','source':'synthetic://len'}
def tool_payload(arguments='{}'):
 return {'messages':[{'role':'assistant','content':None,'tool_calls':[{'id':'call1','type':'function','function':{'name':'docker_tool','arguments':arguments}}]},{'role':'tool','tool_call_id':'call1','content':[{'type':'text','text':'container result'}]}],'tools':[{'type':'function','function':{'name':'docker_tool','parameters':{'type':'object'}}}],'response_format':{'type':'json_object'}}
def test_tool_history_and_null_text_blocks_are_counted_without_network():
 a=count_request(tool_payload(),policy());b=count_request(tool_payload('x'*10002),policy())
 assert b['input_tokens']-a['input_tokens']==10000
 assert all(a['components'][x]>0 for x in ('tool_calls','tool_results','tools_schema','response_format','role_and_call_associations'))
 assert a['estimated_total_input_tokens'] is None
 missing=tool_payload();missing['messages'][0].pop('content');assert count_request(missing,policy())['input_tokens']==a['input_tokens']
 image=tool_payload();image['messages'][1]['content'].append({'type':'image_url','image_url':{'url':'fixture.invalid'}})
 with pytest.raises(DynamicError,match='request_image_count_unknown'):count_request(image,policy())

def test_provider_mock_reaches_shared_real_count_path(tmp_path,monkeypatch):
 import trustfork.runtime.dynamic.token_accounting as accounting
 seen=[];original=accounting.count_request
 def capture(*a,**k):seen.append(a[0]);return original(*a,**k)
 monkeypatch.setattr(accounting,'count_request',capture)
 config=configuration();transport=ProviderTransport(config,mode='mock',journal=tmp_path/'journal',max_requests=1,http=lambda *args:{'status':200,'headers':{},'body':'{}'})
 body={**tool_payload('x'*10000),'model':'exact-fixture','max_tokens':10}
 transport.request('gpt4o',{'url':'https://mock.invalid/v1/chat/completions','method':'POST','body':json.dumps(body)},request_id='mock')
 assert seen==[body]
 rows=[json.loads(line) for line in (tmp_path/'journal').read_text().splitlines()]
 assert rows[0]['token_accounting']['components']['tool_calls']>=10000 and rows[0]['source']=='mock'

def test_active_alias_scope_is_derived_from_frozen_experiment(tmp_path):
 config=configuration();config['logical_bindings']['deepseekflash']['model_id']=None
 from trustfork.runtime.dynamic.model_capabilities import unknown_capability
 config['logical_bindings']['deepseekflash']['capability']=unknown_capability()
 config.update(mode='api',real_api_enabled=True)
 assert validate_bindings(config,formal=True,role_scope='judge')['active_aliases']==['gpt4o']
 assert validate_bindings(config,formal=True,required_aliases=resolve_experiment('p001',team_model='gpt4o').model_refs.values())['formal_ready']
 with pytest.raises(DynamicError,match='unresolved_formal_bindings'):validate_bindings(config,formal=True,required_aliases=resolve_experiment('p001',team_model='deepseekflash').model_refs.values())
 config.update(mode='offline',real_api_enabled=False)
 t=ProviderTransport(config,mode='mock',journal=tmp_path/'guard',http=lambda *a:pytest.fail('No send'),max_requests=1,experiment=resolve_experiment('p001',team_model='gpt4o'))
 with pytest.raises(DynamicError,match='inactive_provider_alias'):t.request('deepseekflash',{},request_id='bad')

@pytest.mark.parametrize('representation',['legacy-full','trajectory-lossless-v1'])
def test_semantic_builder_preserves_sanitizer_public_risk_and_full_roundtrip(representation):
 events=[{'actor_id':'C','event_type':'model_request_submitted','branch_id':'b','event_id':'e','stage_id':'s','stage_epoch':0,'payload':{'actual_input':{'systemPrompt':'Role\n\nPRIVATE_BOUND_GOAL','messages':[{'role':'user','content':'PUBLIC_DANGEROUS_ADVICE'}]}}}]
 view=trajectory_judge_view(events,task={},private_goals={'C':'PRIVATE_BOUND_GOAL'},frozen_state={},final_response='done')
 bundle=build_judge_bundle({'responses':[]},view,scoring_profile='dynamic-homogeneous-v2',goal_spec={'rule':'original harm condition'},annotation_schema={})
 config={'temperature':0,'response_output_budget_tokens':50,'trajectory_output_budget_tokens':100,'trajectory_representation':representation}
 p=prepare_judge_pass(bundle,'trajectory',binding=configuration()['logical_bindings']['gpt4o'],scorer_config=config,counter=len)
 sent=json.loads(p['wire_payload']['messages'][1]['content']);decoded=decode_trajectory(sent) if representation=='trajectory-lossless-v1' else sent
 assert decoded==bundle['views']['trajectory']
 assert 'PRIVATE_BOUND_GOAL' not in json.dumps(sent) and 'PUBLIC_DANGEROUS_ADVICE' in json.dumps(sent)
 assert p['request']['parameters']=={'temperature':0,'max_tokens':100} and p['token_accounting']['input_tokens']==p['input_tokens']
 assert 'ias' not in bundle['formats']['trajectory']
 assert prepare_judge_pass(bundle,'response',binding=configuration()['logical_bindings']['gpt4o'],scorer_config=config,counter=len)['not_applicable']

def test_true_marker_cannot_bypass_isolation():
 with pytest.raises(DynamicError,match='unsanitized_trajectory'):build_judge_bundle({'responses':[]},{'private_goals_removed':True,'trajectory':[{'private_goal':'leak'}]})
 view=trajectory_judge_view([],task={},private_goals={},frozen_state={},final_response='')
 view['trajectory'].append('tamper')
 with pytest.raises(DynamicError,match='unsanitized_trajectory'):build_judge_bundle({'responses':[]},view)

def test_route_tokenizer_cannot_be_copied_to_another_provider():
 b=configuration()['logical_bindings']['gpt4o'];b['model_id']='different'
 with pytest.raises(DynamicError,match='capability_route_mismatch'):route_counting_policy(b)


def test_mock_also_checks_structure_of_unused_routes(tmp_path):
 config=configuration();config['logical_bindings']['deepseekflash']['provider']=7
 with pytest.raises(DynamicError,match='invalid_model_binding'):ProviderTransport(config,mode='mock',journal=tmp_path/'must-not-exist',http=lambda *args:pytest.fail('No send'),max_requests=1,experiment=resolve_experiment('p001',team_model='gpt4o'))
 assert not (tmp_path/'must-not-exist').exists()
