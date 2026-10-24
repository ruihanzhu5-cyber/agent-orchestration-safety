import copy
import json
import pytest
from trustfork.runtime.dynamic.common import DynamicError,config_dir,read_json
from trustfork.runtime.dynamic.schema import validate_contract,validate_schema
from trustfork.runtime.dynamic.events import EventLedger
from trustfork.runtime.dynamic.goals import LAYOUTS
from trustfork.runtime.dynamic.initial_plan import parse_initial_plan
from trustfork.runtime.dynamic.profile_service import FAILURES


def test_shared_rpc_contract_and_event_mutability(tmp_path):
    good={'rpc_id':'rpc','actor_id':'C','opaque_session_id':'session','request_id':'request','branch_id':'branch',
          'task_id':'task','stage_id':'stage','stage_epoch':0,'invocation_id':None,'operation':'execute_turn','payload':{}}
    assert validate_contract('BridgeEnvelope',good)==good
    for key,value in [('private_extra','leak'),('actor_id','Attacker'),('stage_epoch',-1),('stage_epoch',0.5),('payload',[])]:
        with pytest.raises(DynamicError):validate_contract('BridgeEnvelope',{**good,key:value})
    missing={**good};missing.pop('request_id')
    with pytest.raises(DynamicError):validate_contract('BridgeEnvelope',missing)
    ledger=EventLedger(tmp_path/'events.jsonl','branch','task')
    payload={'nested':[]};returned=ledger.append('fixture',payload);payload['nested'].append('later');returned['payload']['nested'].append('other')
    assert ledger.rows[0]['payload']=={'nested':[]}
    validate_contract('EventEnvelope',ledger.rows[0])
    with pytest.raises(DynamicError):validate_contract('EventEnvelope',{**ledger.rows[0],'unknown_field':1})
    for metric in ('RTF','EI'):
        with pytest.raises(DynamicError):validate_contract('ScoreRecord',{'metric':metric,'value':None,'status':'safe_assumed','reason':None,'evidence_refs':[]})


def test_frozen_config_layouts_failures_and_context_refs():
    assert read_json(config_dir()/'history_layouts.json')==LAYOUTS
    assert {key:set(value) for key,value in read_json(config_dir()/'profiles.json')['failure_positions'].items()}==FAILURES
    plan={'plan_status':'delegate','assignments':[{'recipient':'A','task_text':'Read task','context_refs':['private://answer']}],'draft_answer':None}
    with pytest.raises(DynamicError,match='invalid_plan_context_reference'):parse_initial_plan(json.dumps(plan))
    plan['assignments'][0]['context_refs']=['task://current-stage']
    assert parse_initial_plan(json.dumps(plan),allowed_context_refs=['task://current-stage'])['plan']['assignments']


def test_all_frozen_configuration_schemas_reject_unlisted_changes():
    schema=read_json(config_dir()/'frozen_configs.schema.json')
    for name in schema['$defs']:
        value=read_json(config_dir()/name)
        validate_schema(value,{**schema,'$ref':'#/$defs/'+name})
        changed=copy.deepcopy(value);changed['unlisted_experiment_setting']=True
        with pytest.raises(DynamicError):validate_schema(changed,{**schema,'$ref':'#/$defs/'+name})
    validate_schema(read_json(config_dir()/'model_bindings.example.json'),read_json(config_dir()/'model_bindings.schema.json'))
