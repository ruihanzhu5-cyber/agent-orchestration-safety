"""Current Docker/Pi + original paid-bucket semantics with an explicit local mock."""
import json,sys,runpy,importlib.metadata
from pathlib import Path
import pytest
from trustfork.runtime.dynamic.common import repo_root,read_json,write_json,file_hash,digest,DynamicError
from trustfork.runtime.dynamic.provider import ProviderTransport
from trustfork.runtime.dynamic.campaign_budget import CampaignBudget
from trustfork.runtime.dynamic.execution_attempt import migrate_attempts,ExecutionAttempt
from trustfork.agents.pi_dynamic import PiDynamic,ProviderSource
from trustfork.runtime.dynamic.prepared_artifacts import prepare_history,load_history,load_prefix
from trustfork.tools.runtime_judge_review import reconcile_stage
from test_provider_history import MockHistory
from test_homogeneous_end_to_end import judge_replies


def test_compatible_history_budget_and_real_checkpoint_resume_through_final_mock_metrics(tmp_path,monkeypatch):
 import trustfork.runtime.dynamic.provider as module
 monkeypatch.setattr(module,'real_http',lambda *a,**k:(_ for _ in ()).throw(AssertionError('real network forbidden')))
 sys.path.insert(0,str(repo_root()/'tests/dynamic/unit'))
 configured=runpy.run_path(str(repo_root()/'tests/dynamic/unit/test_campaign_budget.py'))['configured_campaign']
 budget=CampaignBudget(tmp_path/'budget.sqlite3',campaign_id='first-api-20261026',segment_id='plan-judge-followup-20261026',segment_cny=20,segment_identity={'identity_hash':'old-test'})
 budget.reserve('old-paid',phase='engineering_smoke',reserved_cost_cny=8,metadata={});budget.submitted('old-paid');budget.settle('old-paid',settled_cost_cny=7,usage={})
 migrate_attempts(budget.path,apply=True,backup=tmp_path/'backup.sqlite3')
 attempt=ExecutionAttempt(budget,tmp_path/'new-attempt',attempt_id='review-offline',parent_attempt='old-test',identity={'execution_code_sha':'synthetic-current-code'})
 cfg=configured(budget.path);cfg['judge_binding']='deepseekflash';cfg['campaign_budget'].update(segment_id=budget.segment_id,segment_cny=20,segment_identity={'identity_hash':'old-test'},must_exist=True)
 for binding in cfg['logical_bindings'].values():binding['capability']['tokenizer'].update(id='o200k_base',version=importlib.metadata.version('tiktoken'),count_method='local-message-content-and-schema-bpe-estimate')
 for limits in cfg['execution_limits'].values():limits.update(requests_per_minute=10000,tokens_per_minute=100000000)
 mock=MockHistory();t=ProviderTransport(cfg,mode='mock',journal=attempt.path/'requests.jsonl',http=mock,max_requests=100)
 parent=PiDynamic('p001',attempt.path/'history',team_model='deepseekflash',provider=t);parent.execution_attempt=attempt
 hpath=parent.out/'history-bundle.json';bundle=prepare_history(parent,ProviderSource(),hpath)
 calls=t.count;hashes={p:file_hash(p) for p in parent.out.rglob('events.jsonl')};history_hash=file_hash(hpath)
 restored=PiDynamic('p001',parent.out,team_model='deepseekflash',provider=t);restored.execution_attempt=attempt
 load_history(restored,hpath)
 repeated=restored.run_history(scripts=ProviderSource())
 assert t.count==calls and file_hash(hpath)==history_hash and all(file_hash(p)==h for p,h in hashes.items())
 assert all(digest(repeated['actor_states'][a])==digest(bundle['history']['actor_states'][a]) for a in ('Main','A','B'))
 # A different coordination identity must not be silently reused.
 original=read_json(hpath);mutated=json.loads(json.dumps(original));mutated['contract']['coordination_contract']['version']='synthetic-old-no-wait'
 mutated.pop('bundle_id');mutated['bundle_id']='history_bundle_'+digest(mutated);write_json(attempt.path/'incompatible-history.json',mutated)
 with pytest.raises(DynamicError,match='history_bundle_target_mismatch'):load_history(restored,attempt.path/'incompatible-history.json')
 r=PiDynamic('p001',attempt.path/'S',team_model='deepseekflash',provider=t,protocol='S');r.execution_attempt=attempt
 history=load_history(r,hpath);stage='prefix/S';identity={'history_bundle_id':bundle['bundle_id'],'prefix_identity':r.prefix_identity()}
 t.request_namespace=attempt.request_id(stage,'model');t.execution_context={'execution_attempt_id':attempt.attempt_id,'execution_stage_id':stage,'execution_review_id':'synthetic-runtime-review'}
 def interrupted_after_checkpoint():
  prefix=r.run_prefix(ProviderSource(),history=history)
  assert prefix['status']=='triggered'
  raise KeyboardInterrupt('injected after durable checkpoint, before stage DB commit')
 with pytest.raises(KeyboardInterrupt):attempt.run(stage,identity,interrupted_after_checkpoint)
 before=t.count
 saved=reconcile_stage(attempt,stage,r.out/'prefix/checkpoint.json','prefix',identity)
 assert t.count==before
 assert attempt.run(stage,identity,lambda:pytest.fail('checkpoint stage replayed'))==saved
 prefix=load_prefix(r,Path(saved['path']))
 stage='t3/S/HP';t.request_namespace=attempt.request_id(stage,'model');t.execution_context['execution_stage_id']=stage
 def branch():
  run=r.run_branch(prefix['checkpoint'],'HP',ProviderSource());return {'status':run['run_status'],'path':str(r.directory/'run.json')}
 result=attempt.run(stage,{'checkpoint':prefix['checkpoint']['checkpoint_id'],'condition':'HP'},branch,artifacts=lambda v:[Path(v['path'])])
 before=t.count
 assert attempt.run(stage,{'checkpoint':prefix['checkpoint']['checkpoint_id'],'condition':'HP'},branch)==result and t.count==before
 path=Path(result['path']);run=read_json(path)
 from trustfork.scoring.dynamic_pipeline import score_run,load_events
 from trustfork.scoring.scoring_versions import rescore_contract,frozen_identity
 from trustfork.tools.judge_dynamic import run_judge_attempt
 score_run(path,mode='test-fixtures');raw=frozen_identity(path);events=load_events(path.parent,run);replies=judge_replies(run,events)
 # Full strict Judge chain with synthetic replies. These anchors are not research judgments.
 for binding in cfg['logical_bindings'].values():binding.update(context_window=1000000,max_output_tokens=65536);binding['capability'].update(effective_context_tokens=1000000,max_output_tokens=65536)
 judged=run_judge_attempt(path,attempt.path/'judge',cfg,mode='mock',scorer_config={'scoring_profile':'dynamic-homogeneous-v2','execution_scope':'engineering_smoke','response_output_budget_tokens':16384,'trajectory_output_budget_tokens':32768,'trajectory_representation':'trajectory-lossless-v2'},mock_replies=replies,max_requests=4,request_namespace=attempt.request_id('score/S/HP','judge'),execution_context={'execution_attempt_id':attempt.attempt_id,'execution_stage_id':'score/S/HP','execution_review_id':'synthetic-runtime-review'})
 assert all(s['status'] in ('completed','not_applicable') for s in judged['pass_states'].values())
 contract=rescore_contract(path,reason='Synthetic reviewed resume integration',annotation_policy='new',new_annotations=attempt.path/'judge/scoring_annotations.json')
 summary=score_run(path,mode='test-fixtures',rescore=contract)
 assert summary['run_id']==run['run_id'] and frozen_identity(path)==raw
 assert budget.segment_summary()['settled_cny']>7 and budget.segment_summary()['remaining_cny']<13
 assert all(row['metadata'].get('execution_attempt_id')=='review-offline' for row in budget.rows() if row['request_id']!='old-paid')
 write_json(attempt.path/'offline-chain-result.json',{'synthetic':True,'real_model_calls':0,'real_judge_calls':0,'source_code':'current working tree during offline regression','model_mock_requests':t.count,'history_reuse_new_requests':0,'checkpoint_reconcile_new_requests':0,'hp_stage_replay_new_requests':0,'judge':judged,'metrics':summary['scores'],'budget':budget.segment_summary(),'old_source_hash_unchanged':True})
