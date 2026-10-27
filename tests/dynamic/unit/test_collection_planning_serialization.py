import json,pytest
from types import SimpleNamespace
from trustfork.runtime.dynamic.initial_plan import planning_contract,parse_initial_plan
from trustfork.runtime.dynamic.history_execution import history_request_context
from trustfork.runtime.dynamic.common import DynamicError

def test_planning_advertises_exact_wire_serialization_without_normalizing_answers():
 c=planning_contract();assert c['serialization_version']=='raw-json-v1'
 assert 'Markdown' in c['instruction'] and 'exactly one JSON object' in c['instruction']
 plan={'plan_status':'no_plan','assignments':[],'draft_answer':None};raw=json.dumps(plan)
 assert parse_initial_plan(raw)['plan']==plan
 with pytest.raises(DynamicError,match='initial_plan_invalid_json'):parse_initial_plan('```json\n'+raw+'\n```')
 errors=[]
 with pytest.raises(DynamicError):parse_initial_plan('not json',repair=lambda raw,instruction:errors.append(instruction) or '```json\n'+json.dumps(plan)+'\n```')
 assert len(errors)==1 and 'Markdown' in errors[0]

def test_history_context_preserves_round_identity_and_scopes_each_fixed_stage():
 base={'execution_review_id':'small-api-collection-20261027','model_generation_group_id':'small-api-collection-20261027/history','other':'kept'}
 attempt=SimpleNamespace(attempt_id='attempt')
 v=history_request_context(base,attempt,'history/H1')
 assert v['execution_review_id']==base['execution_review_id']
 assert v['model_generation_group_id']=='small-api-collection-20261027/history/H1'
 assert v['execution_stage_id']=='history/H1' and v['other']=='kept' and 'execution_stage_id' not in base
