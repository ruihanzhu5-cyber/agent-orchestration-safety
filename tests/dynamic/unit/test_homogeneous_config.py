import copy,json
from collections import Counter
from dataclasses import FrozenInstanceError
import pytest
from trustfork.runtime.dynamic.experiment_config import resolve_experiment,VERSION
from trustfork.tools.generate_dynamic_manifest import generate_plan,auxiliary_plans
from trustfork.runtime.dynamic.common import DynamicError,write_json,digest
from trustfork.agents.pi_dynamic import PiDynamic

def test_frozen_plan_enumeration_and_all_pairings():
 rows=generate_plan();ids={r['plan_run_id'] for r in rows}
 assert len(rows)==len(ids)==1248 and len({r['block_id'] for r in rows})==336
 assert Counter(r['panel'] for r in rows)=={'primary':832,'80_60':128,'no_external_portfolio':64,'r70':32,'self_on_request':32,'reminder':32,'strategy':32,'repeat':64,'late_join':32}
 assert sum(r['mechanism_sample'] for r in rows)==144
 assert len(auxiliary_plans()['history_bundles'])==4 and len(auxiliary_plans()['smoke'])==32
 for r in rows:
  assert set(r['model_refs'].values())=={r['team_model']}
  assert set(r['baseline_plan_refs'])<=ids
  if r['panel']=='no_external_portfolio':assert len(r['baseline_plan_refs'])==2
  if r['protocol']=='F':assert r['matched_S_plan_ref'] in ids
  peers=[x for x in rows if x['block_id']==r['block_id'] and x['condition'][0]==r['condition'][0]]
  assert len({x['profile_hash'] for x in peers})==1
 for team in ('gpt4o','deepseekflash'):
  p=[r for r in rows if r['team_model']==team and r['protocol']=='S' and r['panel']=='primary' and r['condition']=='HP']
  assert Counter(r['profile_corpus_id'] for r in p)=={f'R{i}':13 for i in range(1,5)}
  for c in {r['case_id'] for r in p}:
   paired=[r for r in p if r['case_id']==c];assert {r['q'] for r in paired}=={'C','D'}
   assert len({r['display_order'][0]==r['q'] for r in paired})==1

def test_immutable_config_and_runtime_models(tmp_path):
 cfg=resolve_experiment('p001',team_model='deepseekflash')
 with pytest.raises(FrozenInstanceError):cfg.q='D'
 refs=cfg.model_refs;refs['A']='gpt4o';assert cfg.model_refs['A']=='deepseekflash'
 runtime=PiDynamic('p001',tmp_path,team_model='deepseekflash')
 assert set(runtime.model_refs.values())=={'deepseekflash'}
 assert runtime.history_task_ids==['p002','p007']
 from types import SimpleNamespace
 runtime.ledger=SimpleNamespace(branch_id='fixture');runtime.membership=SimpleNamespace(status=lambda a:'admitted')
 runtime._bind_profiles('HA')
 assert runtime.q=='C' and runtime.profile_metadata['display_order']==['C','D']
 with pytest.raises(DynamicError):PiDynamic('p001',tmp_path/'bad',layout='P1')

def test_prefix_target_excludes_suffix_factors_but_binds_team_and_history(tmp_path):
 a=PiDynamic('p001',tmp_path/'a',team_model='gpt4o');a.history={'history_bundle_id':'fixture','actor_states':{}}
 snapshot={'task_id':'p001','history':a.history,'bindings':{'prefix_identity':a.prefix_identity()}}
 for protocol,panel,repeat in [('F','primary',0),('S','repeat',2),('L','late_join',0)]:
  b=PiDynamic('p001',tmp_path/(protocol+panel),team_model='gpt4o',protocol=protocol,panel=panel,repeat_id=repeat);b.history=a.history
  b.validate_prefix_target(snapshot)
 wrong=PiDynamic('p001',tmp_path/'wrong',team_model='deepseekflash');wrong.history=a.history
 with pytest.raises(DynamicError,match='prefix_target_mismatch'):wrong.validate_prefix_target(snapshot)
 a.history={'history_bundle_id':'different'}
 with pytest.raises(DynamicError,match='prefix_target_mismatch'):a.validate_prefix_target(snapshot)

def test_history_bundle_hash_provenance_scope_and_no_new_execution_on_reuse(tmp_path):
 from trustfork.runtime.dynamic.history import History
 from trustfork.runtime.dynamic.prepared_artifacts import prepare_history,load_history
 runtime=PiDynamic('p001',tmp_path/'source',team_model='gpt4o');h=History()
 for task in runtime.history_task_ids:h.add_task(task,{a:{'config':{'actor_id':a,'task_id':task},'messages':[]} for a in ('Main','A','B')},synthetic=True,status='refused')
 runtime.run_history=lambda **kw:h.export()
 path=tmp_path/'bundle.json';bundle=prepare_history(runtime,None,path)
 target=PiDynamic('p024',tmp_path/'target',team_model='gpt4o')
 loaded=load_history(target,path,reuse_journal=tmp_path/'reuse.jsonl')
 assert set(loaded['actor_states'])=={'Main','A','B'} and loaded['actor_states']['A'][0]['status']=='refused'
 assert json.loads((tmp_path/'reuse.jsonl').read_text())['new_history_task_attempts']==0
 wrong=PiDynamic('p024',tmp_path/'wrong',team_model='deepseekflash')
 with pytest.raises(DynamicError,match='history_bundle_target_mismatch'):load_history(wrong,path)
 bundle['history']['actor_states']['A'][0]['session']['messages'].append('tampered');write_json(path,bundle)
 with pytest.raises(DynamicError,match='history_bundle_hash_mismatch'):load_history(target,path)
