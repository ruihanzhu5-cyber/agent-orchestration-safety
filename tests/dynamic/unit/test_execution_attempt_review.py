import json,sqlite3
from pathlib import Path
import pytest
from trustfork.runtime.dynamic.common import DynamicError,write_json,file_hash
from trustfork.runtime.dynamic.campaign_budget import CampaignBudget

def existing(tmp_path):
 path=tmp_path/'original.sqlite3'
 b=CampaignBudget(path,campaign_id='first-api-20261026',segment_id='plan-judge-followup-20261026',segment_cny=20,segment_identity={'identity_hash':'old-v5'})
 b.reserve('old-paid',phase='engineering_smoke',reserved_cost_cny=8,metadata={});b.submitted('old-paid');b.settle('old-paid',settled_cost_cny=7,usage={})
 return b


def test_migration_dry_run_preserves_original_facts_and_new_attempt_inherits(tmp_path):
 from trustfork.runtime.dynamic.execution_attempt import migrate_attempts,ExecutionAttempt
 b=existing(tmp_path);before=file_hash(b.path)
 dry=migrate_attempts(b.path,apply=False)
 assert dry['needs_migration'] and file_hash(b.path)==before
 result=migrate_attempts(b.path,apply=True,backup=tmp_path/'backup.sqlite3')
 assert result['original_facts_unchanged'] and (tmp_path/'backup.sqlite3').exists()
 a=ExecutionAttempt(b,tmp_path/'new-out',attempt_id='review-1',parent_attempt='old-v5',identity={'code_sha':'new','config_hash':'new','protocol':'wait-v1'})
 assert a.inspect()['segment']['remaining_cny']==13
 calls=[]
 def run():
  calls.append(1);p=tmp_path/'result.json';write_json(p,{'status':'complete'});return {'path':str(p)}
 first=a.run('formal/fixture',{'scorer':'v7'},run,artifacts=lambda r:[Path(r['path'])])
 assert a.run('formal/fixture',{'scorer':'v7'},run)==first and len(calls)==1
 # Same attempt in another output directory is still one execution and one bucket.
 other=ExecutionAttempt(b,tmp_path/'other',attempt_id='review-1',parent_attempt='old-v5',identity={'code_sha':'new','config_hash':'new','protocol':'wait-v1'})
 assert other.run('formal/fixture',{'scorer':'v7'},run)==first and len(calls)==1
 with pytest.raises(DynamicError,match='execution_attempt_identity_mismatch'):ExecutionAttempt(b,tmp_path/'third',attempt_id='review-1',parent_attempt='old-v5',identity={'code_sha':'different'})
 new=ExecutionAttempt(b,tmp_path/'next',attempt_id='review-2',parent_attempt='review-1',identity={'code_sha':'next'})
 assert new.inspect()['segment']['remaining_cny']==13 and new.request_id('history/H1','r1').startswith('review-2.')


def test_interrupted_stage_unknown_charge_not_replayed_and_artifact_reconcile(tmp_path):
 from trustfork.runtime.dynamic.execution_attempt import migrate_attempts,ExecutionAttempt
 b=existing(tmp_path);migrate_attempts(b.path,apply=True,backup=tmp_path/'backup')
 a=ExecutionAttempt(b,tmp_path/'a',attempt_id='review-1',parent_attempt='old',identity={'code_sha':'new'})
 calls=[]
 def crash():
  calls.append(1);rid=a.request_id('prefix/S','r1')
  b.reserve(rid,phase='engineering_smoke',reserved_cost_cny=2,metadata={'execution_attempt_id':a.attempt_id,'execution_stage_id':'prefix/S'})
  b.submitted(rid)
  raise KeyboardInterrupt('crash after submitted')
 with pytest.raises(KeyboardInterrupt):a.run('prefix/S',{'protocol':'v2'},crash)
 with pytest.raises(DynamicError,match='execution_stage_requires_reconciliation'):a.run('prefix/S',{'protocol':'v2'},crash)
 assert len(calls)==1 and a.inspect()['unknown_submitted_requests']
 assert b.segment_summary()['remaining_cny']==11
 # No checkpoint: cannot manufacture recovery from the HTTP accounting record.
 with pytest.raises(DynamicError):a.reconcile('prefix/S',{'protocol':'v2'},lambda:(_ for _ in ()).throw(DynamicError('checkpoint_missing','missing')))
 checkpoint=tmp_path/'complete-checkpoint.json';write_json(checkpoint,{'validated_complete_artifact':True})
 # This generic transition requires caller-supplied deterministic contract validation.
 recovered=a.reconcile('prefix/S',{'protocol':'v2'},lambda:{'path':str(checkpoint)},artifacts=lambda r:[Path(r['path'])])
 assert a.run('prefix/S',{'protocol':'v2'},crash)==recovered and len(calls)==1
 assert b.segment_summary()['remaining_cny']==11


def test_completed_artifact_mutation_and_protocol_mismatch_fail(tmp_path):
 from trustfork.runtime.dynamic.execution_attempt import migrate_attempts,ExecutionAttempt
 b=existing(tmp_path);migrate_attempts(b.path,apply=True,backup=tmp_path/'backup')
 a=ExecutionAttempt(b,tmp_path/'a',attempt_id='review-1',parent_attempt='old',identity={'code_sha':'new'})
 p=tmp_path/'h.json';write_json(p,{'frozen':'H1'})
 a.run('history/H1',{'protocol':'old'},lambda:{'path':str(p)},artifacts=lambda r:[p])
 with pytest.raises(DynamicError,match='execution_stage_identity_mismatch'):a.run('history/H1',{'protocol':'new'},lambda:None)
 p.write_text('changed')
 with pytest.raises(DynamicError,match='execution_stage_artifact_changed'):a.run('history/H1',{'protocol':'old'},lambda:None)


def test_atomic_clone_failure_never_publishes_half_copy_and_can_retry(tmp_path,monkeypatch):
 from trustfork.runtime.dynamic.followup import clone_frozen_run
 import trustfork.runtime.dynamic.followup as m
 source=tmp_path/'source';source.mkdir()
 write_json(source/'run.json',{'run_id':'original','run_manifest_path':'manifest.json','events_path':'events.jsonl','prefix_events_path':'prefix-events.json'})
 for name in ('manifest.json','events.jsonl','prefix-events.json','private_bindings.json','profile_metadata.json','delivery_receipts.json'):write_json(source/name,{'synthetic':name})
 write_json(source/'scoring/current_version.json',{'version':'original'})
 monkeypatch.setattr(m,'frozen_identity',lambda p:{'run_hash':file_hash(Path(p))})
 original=m.shutil.copyfile;calls=[]
 def fail(a,b,*args,**kwargs):
  calls.append(1)
  if len(calls)==3:raise OSError('injected interrupted copy')
  return original(a,b,*args,**kwargs)
 monkeypatch.setattr(m.shutil,'copyfile',fail)
 with pytest.raises(OSError):clone_frozen_run(source/'run.json',tmp_path/'dest')
 assert not (tmp_path/'dest').exists()
 monkeypatch.setattr(m.shutil,'copyfile',original)
 path=clone_frozen_run(source/'run.json',tmp_path/'dest')
 assert clone_frozen_run(source/'run.json',tmp_path/'dest')==path
 assert (path.parent/'copy-manifest.json').exists()


def runner_mock(tmp_path,monkeypatch):
 from trustfork.runtime.dynamic.execution_attempt import migrate_attempts,ExecutionAttempt
 from trustfork.tools.runtime_judge_review import ReviewRunner
 from test_campaign_budget import configured_campaign
 import trustfork.tools.runtime_judge_review as module
 b=existing(tmp_path);migrate_attempts(b.path,apply=True,backup=tmp_path/'backup')
 cfg=configured_campaign(b.path);cfg['judge_binding']='deepseekflash'
 cfg['campaign_budget'].update(segment_id=b.segment_id,segment_cny=20,segment_identity={'identity_hash':'old-v5'},must_exist=True)
 for binding in cfg['logical_bindings'].values():
  binding.update(context_window=1000000,max_output_tokens=393216)
  binding['capability'].update(effective_context_tokens=1000000,max_output_tokens=393216)
 a=ExecutionAttempt(b,tmp_path/'out',attempt_id='review-1',parent_attempt='old-v5',identity={'execution_code_sha':'synthetic-offline-sha'})
 monkeypatch.setattr(module,'parent_sources',lambda parent:({'files':{},'runs':{}},[]))
 return ReviewRunner(tmp_path,a,cfg,mode='mock'),b


def test_formal_runner_exact_configuration_all_facts_and_no_replay(tmp_path,monkeypatch):
 from trustfork.runtime.dynamic.common import read_json,canonical
 from test_formal_judge_followup import oracle_annotations
 from test_first_api_judge import reply
 runner,b=runner_mock(tmp_path,monkeypatch);seen=[]
 def factory(stage):
  def http(url,body,key,timeout):
   assert key=='mock-no-credential';wire=json.loads(body);seen.append(wire)
   kind=stage.split('/')[1];f=read_json(runner.path/'fixtures'/kind/'source.json')
   assert 'oracle' not in wire['messages'][1]['content']
   if kind in ('response_success','response_refusal'):
    value={'response_judgements':{k:{**v,'status':'complete','evidence_refs':['response://'+k]} for k,v in f['oracle']['responses'].items()}}
   elif kind=='no_opportunity':
    value={'trajectory_judgements':{k:{'value':f['oracle'][k],'status':'complete','evidence_refs':[f['events'][-1]['branch_id']+'::'+f['events'][-1]['event_id']]} for k in ('terminal_safety','task_utility')},'event_ledger_complete':True,'attempt_coverage_complete':True,'opportunity_annotations':[{'metric_id':m,'actor_id':a,'opportunity_state':'absent','status':'not_applicable','anchor':None,'evidence_refs':[]} for a in ('Main','A','B','C','D') for m in ('SAF_visible','VF_opportunity','EI_update')]}
   else:value=oracle_annotations(f)
   response=reply(json.dumps(value));body=json.loads(response['body']);body['usage']={'prompt_tokens':10,'completion_tokens':5};response['body']=json.dumps(body);return response
  return http
 runner.http_factory=factory
 plan=runner.freeze_plan()
 assert len(plan['cases'])==9 and sum(not c['not_applicable'] for c in plan['cases'])==8
 for c in plan['cases']:
  prepared=read_json(Path(c['prepared_path']))
  assert prepared['output_budget']==(65536 if c['pass_name']=='trajectory' else 16384)
 result=runner.formal();assert result['status']=='completed' and all(result['gates'].values())
 assert len(seen)==8 and result['actual_requests']==8
 assert runner.formal()==result and len(seen)==8
 assert b.segment_summary()['settled_cny']>7 and b.segment_summary()['remaining_cny']<13
 assert len([r for r in b.rows() if r['metadata'].get('execution_review_id')])==8


def test_formal_failure_blocks_dependency_not_response_and_no_oracle_feedback(tmp_path,monkeypatch):
 from test_first_api_judge import reply
 runner,b=runner_mock(tmp_path,monkeypatch)
 runner.http_factory=lambda stage:(lambda *args:reply('{}'))
 result=runner.formal()
 assert not any(result['gates'].values()) and result['actual_requests']==4 # first bad trajectory and first bad response, one repair each
 assert sum(r['status']=='not_started' for r in result['cases'])==6
 queued=next(r for r in result['cases'] if r['fixture_id']=='queued_only')
 assert queued['status']=='not_applicable' and queued['requests']==0


def test_formal_group_limit_shared_across_transports_and_attempts(tmp_path):
 b=existing(tmp_path)
 for i in range(24):
  b.reserve('formal-'+str(i),phase='interface_probe',reserved_cost_cny=.001,metadata={'validation_group_id':'review/formal','group_request_limit':24,'execution_attempt_id':'attempt-'+str(i%2)})
  b.submitted('formal-'+str(i));b.settle('formal-'+str(i),settled_cost_cny=.001,usage={})
 with pytest.raises(DynamicError,match='validation_request_budget_exhausted'):b.reserve('25',phase='interface_probe',reserved_cost_cny=.001,metadata={'validation_group_id':'review/formal','group_request_limit':24})
 assert b.segment_summary()['settled_cny']==pytest.approx(7.024)


def test_finished_stages_resume_after_history_prefix_and_hp_without_reexecution(tmp_path):
 from trustfork.runtime.dynamic.execution_attempt import migrate_attempts,ExecutionAttempt
 b=existing(tmp_path);migrate_attempts(b.path,apply=True,backup=tmp_path/'backup')
 a=ExecutionAttempt(b,tmp_path/'out',attempt_id='review-1',parent_attempt='old',identity={'execution_code_sha':'synthetic'})
 calls=[]
 def do(stage):
  calls.append(stage);p=a.path/(stage.replace('/','-')+'.json');write_json(p,{'stage':stage});return {'path':str(p),'status':'completed'}
 stages=['history/H1','history/H2','prefix/S','t3/S/HP']
 for stage in stages:a.run(stage,{'stage':stage},lambda stage=stage:do(stage),artifacts=lambda r:[Path(r['path'])])
 restored=ExecutionAttempt(b,a.path,attempt_id='review-1',parent_attempt='old',identity={'execution_code_sha':'synthetic'})
 for stage in stages:restored.run(stage,{'stage':stage},lambda stage=stage:do(stage))
 restored.run('t3/S/HA',{'stage':'t3/S/HA'},lambda:do('t3/S/HA'))
 assert calls==stages+['t3/S/HA'] and b.segment_summary()['remaining_cny']==13


def test_typed_reconcile_never_turns_missing_old_prefix_into_checkpoint(tmp_path):
 from trustfork.runtime.dynamic.execution_attempt import migrate_attempts,ExecutionAttempt
 from trustfork.tools.runtime_judge_review import reconcile_stage
 b=existing(tmp_path);migrate_attempts(b.path,apply=True,backup=tmp_path/'backup')
 a=ExecutionAttempt(b,tmp_path/'out',attempt_id='review-1',parent_attempt='old',identity={'execution_code_sha':'synthetic'})
 identity={'history_bundle_id':'missing','prefix_identity':{}}
 def interrupted():raise KeyboardInterrupt()
 with pytest.raises(KeyboardInterrupt):a.run('prefix/S',identity,interrupted)
 with pytest.raises(DynamicError,match='reconcile_artifact_missing'):reconcile_stage(a,'prefix/S',a.path/'checkpoint.json','prefix',identity)
 with pytest.raises(DynamicError,match='execution_stage_requires_reconciliation'):a.run('prefix/S',identity,lambda:None)


def test_fixed_model_generation_cannot_be_resampled_in_new_attempt(tmp_path):
 b=existing(tmp_path)
 meta={'execution_attempt_id':'one','model_generation_group_id':'review/history/H1'}
 b.reserve('first',phase='engineering_smoke',reserved_cost_cny=.1,metadata=meta);b.submitted('first');b.settle('first',settled_cost_cny=.01,usage={})
 b.reserve('same-owner',phase='engineering_smoke',reserved_cost_cny=.1,metadata=meta)
 with pytest.raises(DynamicError,match='fixed_generation_already_started'):b.reserve('resample',phase='engineering_smoke',reserved_cost_cny=.1,metadata={**meta,'execution_attempt_id':'two'})


def test_new_attempt_reuses_parent_compatible_history_without_selecting_success(tmp_path):
 from trustfork.runtime.dynamic.execution_attempt import migrate_attempts,ExecutionAttempt
 b=existing(tmp_path);migrate_attempts(b.path,apply=True,backup=tmp_path/'backup')
 parent=ExecutionAttempt(b,tmp_path/'one',attempt_id='one',parent_attempt='legacy',identity={'execution_code_sha':'old-code'})
 p=parent.path/'h2.json';write_json(p,{'status':'budget_ended','synthetic':True})
 previous=parent.run('history/H2',{'contract':'compatible'},lambda:{'path':str(p),'status':'budget_ended'},artifacts=lambda r:[p])
 child=ExecutionAttempt(b,tmp_path/'two',attempt_id='two',parent_attempt='one',identity={'execution_code_sha':'new-cli-only'})
 assert child.reuse_parent_stage('history/H2',{'contract':'compatible'})
 assert child.run('history/H2',{'contract':'compatible'},lambda:pytest.fail('history resampled'))==previous
 assert b.segment_summary()['remaining_cny']==13


def test_reconnecting_same_attempt_preserves_old_transport_journal(tmp_path,monkeypatch):
 runner,b=runner_mock(tmp_path,monkeypatch);runner.http_factory=lambda stage:(lambda *a:pytest.fail('no request expected'))
 out=runner.path/'deepseek/history';first=runner.transport('history',out,kind='model',limit=240)
 write_json(first.journal,{'status':'synthetic_previous_connection','requests_complete_in_stage_records':True})
 original_hash=file_hash(first.journal)
 second=runner.transport('history',out,kind='model',limit=240)
 assert second.journal!=first.journal and file_hash(first.journal)==original_hash
 assert second.execution_context['execution_attempt_id']==runner.attempt.attempt_id
 assert second.campaign.segment_id==b.segment_id and second.count==0
 assert not second.journal.exists() and b.segment_summary()['settled_cny']==7
