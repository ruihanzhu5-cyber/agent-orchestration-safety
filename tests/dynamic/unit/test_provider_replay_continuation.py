import json,pytest
from pathlib import Path
from trustfork.runtime.dynamic.common import write_json,DynamicError
from trustfork.runtime.dynamic.campaign_budget import CampaignBudget
from trustfork.runtime.dynamic.execution_attempt import ExecutionAttempt,migrate_attempts
from trustfork.runtime.dynamic.provider_replay_continuation import verified_replay_parent,ERROR

def fixture(tmp_path,unknown=False):
 b=CampaignBudget(tmp_path/'b.sqlite3',campaign_id='first-api-20261026',segment_id='plan-judge-followup-20261026',segment_cny=20,segment_identity={'source':'original'})
 migrate_attempts(b.path,apply=True,backup=tmp_path/'before.sqlite3');a=ExecutionAttempt(b,tmp_path/'attempt',attempt_id='source',parent_attempt='old',identity={'execution_code_sha':'old'})
 prefix=a.path/'deepseek/blocks/S/prepared-prefix.json';write_json(prefix,{'checkpoint':'retained-source'})
 write_json(a.path/'deepseek/history/history-bundle.json',{'source':'retained history'})
 a.run('prefix/S',{'identity':'same'},lambda:{'path':str(prefix),'status':'completed'},artifacts=lambda v:[prefix])
 run=prefix.parent/'HP/attempt-0/run.json';write_json(run,{'run_status':'infra_error'})
 (run.parent/'events.jsonl').write_text(json.dumps({'event_type':'model_response','request_id':'blocked-before-http','payload':{'response':{'errorMessage':ERROR}}})+'\n')
 def fail():raise DynamicError('pi_generation_failed',ERROR)
 with pytest.raises(DynamicError):a.run('t3/S/HP',{'identity':'same'},fail)
 b.reserve('actual-startup',phase='engineering_smoke',reserved_cost_cny=.01,metadata={'execution_attempt_id':'source','execution_stage_id':'t3/S/HP','kind':'model'});b.submitted('actual-startup')
 b.settle('actual-startup',settled_cost_cny=None if unknown else .001,usage={})
 return b,a,run

def test_replay_continuation_keeps_failed_attempt_and_only_permits_one_known_interface_retry(tmp_path):
 b,a,run=fixture(tmp_path);before=b.rows();proof=verified_replay_parent(b,'source')
 assert proof['blocked_before_http']==['blocked-before-http'] and proof['source_attempt']=='source' and b.rows()==before
 assert a.inspect()['stages'][1]['state']=='failed'
 ExecutionAttempt(b,tmp_path/'child',attempt_id='child',parent_attempt='source',identity={'execution_code_sha':'fixed','provider_replay_continuation':proof})
 with pytest.raises(DynamicError,match='replay_continuation_limit'):verified_replay_parent(b,'source')

def test_valid_or_resource_ended_behavior_cannot_be_resampled(tmp_path):
 b,a,run=fixture(tmp_path)
 for status in ('valid_behavior','resource_ended'):
  write_json(run,{'run_status':status})
  with pytest.raises(DynamicError,match='replay_valid_behavior_forbidden'):verified_replay_parent(b,'source')

def test_unknown_request_still_blocks_this_infrastructure_retry(tmp_path):
 b,a,run=fixture(tmp_path,unknown=True)
 with pytest.raises(DynamicError,match='replay_unknown_request_forbidden'):verified_replay_parent(b,'source')

def test_t3_transport_has_uniform_extended_limit_and_only_failed_hp_changes_generation_group(tmp_path,monkeypatch):
 from test_campaign_budget import configured_campaign
 from trustfork.tools.small_api_collection import CollectionRunner
 from trustfork.tools import runtime_judge_review
 monkeypatch.setattr(runtime_judge_review,'parent_sources',lambda p:({'synthetic-parent':'sealed'},[]))
 b,a,run=fixture(tmp_path);cfg=configured_campaign(b.path);cfg['judge_binding']='deepseekflash'
 a.identity.update(t3_budget_override={'request_limit':240,'token_limit':384000,'stage_seconds':3600},provider_replay_continuation={'source_attempt':'source'})
 runner=CollectionRunner(tmp_path/'parent',a,cfg,mode='mock',http_factory=lambda stage:lambda *args:pytest.fail('No HTTP in transport initialization test'))
 hp=runner.transport('t3/S/HP',tmp_path/'hp');ha=runner.transport('t3/S/HA',tmp_path/'ha')
 assert hp.limit==ha.limit==240 and hp.count==ha.count==0
 assert '/provider-replay-fix/source/' in hp.execution_context['model_generation_group_id']
 assert ha.execution_context['model_generation_group_id']=='small-api-collection-20261027/t3/S/HA'
