import pytest
from trustfork.runtime.dynamic.common import write_json,DynamicError,file_hash
from trustfork.runtime.dynamic.campaign_budget import CampaignBudget
from trustfork.runtime.dynamic.execution_attempt import ExecutionAttempt,migrate_attempts
from trustfork.tools.small_api_collection import verified_network_restart,stage_execution_origin,CollectionRunner

def fixture(tmp_path):
 b=CampaignBudget(tmp_path/'b.sqlite3',campaign_id='first-api-20261026',segment_id='plan-judge-followup-20261026',segment_cny=20,segment_identity={'source':'original'})
 migrate_attempts(b.path,apply=True,backup=tmp_path/'before.sqlite3')
 a=ExecutionAttempt(b,tmp_path/'attempt',attempt_id='source',parent_attempt='old',identity={'execution_code_sha':'original-behavior-sha'})
 prefix=a.path/'deepseek/blocks/S/prepared-prefix.json';write_json(prefix,{'checkpoint':'same-original-checkpoint'})
 write_json(a.path/'deepseek/history/history-bundle.json',{'source':'same-history'})
 a.run('prefix/S',{'identity':'same'},lambda:{'path':str(prefix),'status':'completed'},artifacts=lambda v:[prefix])
 hp=prefix.parent/'HP/attempt-0/run.json';write_json(hp,{'run_status':'valid_behavior'})
 a.run('t3/S/HP',{'identity':'same'},lambda:{'path':str(hp),'status':'valid_behavior'},artifacts=lambda v:[hp])
 failed=prefix.parent/'HA/attempt-0';write_json(failed/'run.json',{'run_status':'infra_error'})
 write_json(failed/'partial-state.json',{'errors':[],'quiesce':{'status':'quiesced','active_at_deadline':[]},'freeze':{'status':'frozen'}})
 write_json(failed/'control/transport-metrics.json',dict(bridge_exit_code=0,transport_failure=None,reader_alive=False,processor_alive=False,unpersisted_tail_bytes=0,unprocessed_tail_bytes=0,reader_closed=True))
 def fail():raise DynamicError('provider_transport_unknown','network outage')
 with pytest.raises(DynamicError):a.run('t3/S/HA',{'identity':'same'},fail)
 b.reserve('interrupted',phase='engineering_smoke',reserved_cost_cny=.01,metadata={'execution_attempt_id':'source','execution_stage_id':'t3/S/HA','kind':'model'})
 b.submitted('interrupted');b.settle('interrupted',settled_cost_cny=None,usage={})
 return b,a,failed,hp

def test_network_restart_preserves_first_cell_and_unknown_reservation_and_is_bounded(tmp_path):
 b,a,failed,hp=fixture(tmp_path);rows=b.rows();hashed=file_hash(hp)
 proof=verified_network_restart(b,'source')
 assert proof['completed_HP_preserved'] and proof['only_restarted_cell']=='S/HA'
 assert proof['unknown_charge_requests_retained']==['interrupted']
 assert b.rows()==rows and file_hash(hp)==hashed
 child=ExecutionAttempt(b,tmp_path/'child',attempt_id='child',parent_attempt='source',identity={'execution_code_sha':'new-controller','network_restart':proof})
 assert child.reuse_parent_stage('t3/S/HP',{'identity':'same'})
 assert stage_execution_origin(b,'child','t3/S/HP')=={'attempt_id':'source','code_sha':'original-behavior-sha'}
 assert not child.reuse_parent_stage('t3/S/HA',{'identity':'same'})
 grandchild=ExecutionAttempt(b,tmp_path/'grandchild',attempt_id='grandchild',parent_attempt='child',identity={'execution_code_sha':'third-controller'})
 assert grandchild.reuse_parent_stage('t3/S/HP',{'identity':'same'})
 assert stage_execution_origin(b,'grandchild','t3/S/HP')['code_sha']=='original-behavior-sha'
 with pytest.raises(DynamicError,match='network_restart_limit'):verified_network_restart(b,'source')

def test_network_restart_rejects_valid_second_cell_and_live_bridge(tmp_path):
 b,a,failed,hp=fixture(tmp_path)
 for status in ('valid_behavior','resource_ended'):
  write_json(failed/'run.json',{'run_status':status})
  with pytest.raises(DynamicError,match='network_restart_not_verified'):verified_network_restart(b,'source')
 write_json(failed/'run.json',{'run_status':'infra_error'})
 p=failed/'control/transport-metrics.json'
 import json
 values=json.loads(p.read_text());values['reader_alive']=True;write_json(p,values)
 with pytest.raises(DynamicError,match='network_restart_not_verified'):verified_network_restart(b,'source')

def test_network_restart_group_only_changes_interrupted_second_cell(tmp_path,monkeypatch):
 from test_campaign_budget import configured_campaign
 from trustfork.tools import runtime_judge_review
 monkeypatch.setattr(runtime_judge_review,'parent_sources',lambda p:({'synthetic-parent':'sealed'},[]))
 b,a,failed,hp=fixture(tmp_path);cfg=configured_campaign(b.path);cfg['judge_binding']='deepseekflash'
 a.identity.update(network_restart={'source_attempt':'source'},t3_budget_override={'request_limit':240,'token_limit':384000,'stage_seconds':3600})
 runner=CollectionRunner(tmp_path/'parent',a,cfg,mode='mock',http_factory=lambda stage:lambda *args:pytest.fail('No HTTP in initialization'))
 for stage in ('t3/S/HP','t3/S/HA','t3/F/HP','t3/F/HA'):
  t=runner.transport(stage,tmp_path/stage)
  assert t.limit==240 and t.count==0
  assert ('/network-restart/source/' in t.execution_context['model_generation_group_id'])==(stage=='t3/S/HA')
