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

def test_extra_metadata_repair_names_allowed_fields_without_accepting_extra_fields():
 original={'plan_status':'answer_ready','assignments':[],'draft_answer':'Already known answer','serialization_version':'raw-json-v1'}
 seen=[]
 def repair(raw,instruction):
  seen.append(instruction)
  return json.dumps({k:v for k,v in json.loads(raw).items() if k!='serialization_version'})
 result=parse_initial_plan(json.dumps(original),repair=repair)
 assert result['plan']['draft_answer']==original['draft_answer'] and result['format_repaired']
 assert len(seen)==1 and 'ONLY root fields are plan_status, assignments, draft_answer' in seen[0]
 assert 'serialization_version' in seen[0] and 'invalid_fields' in seen[0]
 with pytest.raises(DynamicError,match='invalid_fields'):parse_initial_plan(json.dumps(original),repair=lambda *args:json.dumps(original))

def test_h2_retry_requires_recorded_serialization_failure_and_all_settled(tmp_path):
 from trustfork.runtime.dynamic.campaign_budget import CampaignBudget
 from trustfork.runtime.dynamic.execution_attempt import ExecutionAttempt,migrate_attempts
 from trustfork.tools.small_api_collection import verified_h2_serialization_retry
 from trustfork.runtime.dynamic.common import write_json
 b=CampaignBudget(tmp_path/'b.sqlite3',campaign_id='first-api-20261026',segment_id='plan-judge-followup-20261026',segment_cny=20,segment_identity={'source':'retained'})
 migrate_attempts(b.path,apply=True,backup=tmp_path/'backup.sqlite3')
 a=ExecutionAttempt(b,tmp_path/'parent',attempt_id='parent',parent_attempt='old',identity={'execution_code_sha':'before'})
 path=tmp_path/'task.json'
 write_json(path,{'record':{'status':'failed_history_retained','task_id':'p007','termination_reason':'invalid_fields'}})
 a.run('history/H2',{'contract':'same'},lambda:{'status':'failed_history_retained','path':str(path)},artifacts=lambda v:[path])
 b.reserve('h2',phase='engineering_smoke',reserved_cost_cny=.01,metadata={'execution_attempt_id':'parent','execution_stage_id':'history/H2'});b.submitted('h2')
 with pytest.raises(DynamicError,match='history_retry_unknown_requests'):verified_h2_serialization_retry(b,'parent')
 b.settle('h2',settled_cost_cny=.001,usage={})
 retry=verified_h2_serialization_retry(b,'parent');assert retry['stage']=='history/H2'
 child=ExecutionAttempt(b,tmp_path/'child',attempt_id='child',parent_attempt='parent',identity={'history_serialization_retry':retry})
 assert '/serialization-repair/parent/' in history_request_context({'execution_review_id':'round'},child,'history/H2')['model_generation_group_id']
 assert history_request_context({'execution_review_id':'round'},child,'history/H1')['model_generation_group_id']=='round/history/H1'
 with pytest.raises(DynamicError,match='history_retry_limit'):verified_h2_serialization_retry(b,'parent')

def test_h2_success_is_not_a_reason_to_resample(tmp_path):
 from trustfork.runtime.dynamic.campaign_budget import CampaignBudget
 from trustfork.runtime.dynamic.execution_attempt import ExecutionAttempt,migrate_attempts
 from trustfork.tools.small_api_collection import verified_h2_serialization_retry
 b=CampaignBudget(tmp_path/'b.sqlite3',campaign_id='first-api-20261026',segment_id='plan-judge-followup-20261026',segment_cny=20,segment_identity={'source':'retained'})
 migrate_attempts(b.path,apply=True,backup=tmp_path/'backup.sqlite3')
 a=ExecutionAttempt(b,tmp_path/'parent',attempt_id='parent',parent_attempt='old',identity={'execution_code_sha':'before'})
 a.run('history/H2',{'contract':'same'},lambda:{'status':'budget_ended'})
 with pytest.raises(DynamicError,match='history_retry_not_verified'):verified_h2_serialization_retry(b,'parent')
