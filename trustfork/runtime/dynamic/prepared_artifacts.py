"""Explicit immutable history and prefix files. No global cache or live sources."""
import copy,subprocess
from pathlib import Path
from .common import digest,read_json,write_json,DynamicError,repo_root,file_hash
from .artifacts import append_jsonl
from .case_loader import load_case
from .checkpoints import validate_checkpoint
def binding_hash(runtime):
 return digest((runtime.resolved_api_bindings or {}).get('logical_bindings',{}).get(runtime.main_model))
def history_contract(runtime):
 return {'experiment_version':runtime.experiment.experiment_version,'team_model':runtime.main_model,
  'history_pair_id':runtime.experiment.history_pair_id,'task_ids':runtime.history_task_ids,
  'team_binding_hash':binding_hash(runtime),'source_asset_hashes':{c:load_case(c)['deployed_asset_hash'] for c in runtime.history_task_ids},
  'generation_config_hash':digest({'normal_goal':__import__('trustfork.runtime.dynamic.goals',fromlist=['NORMAL_GOAL']).NORMAL_GOAL,
   'budget':[120,48000,4096,1200],'temperature':0.2,'controller':file_hash(repo_root()/'trustfork/agents/pi_dynamic.py'),
   'history_executor':file_hash(repo_root()/'trustfork/runtime/dynamic/history_execution.py')})}
def prepare_history(runtime,source,path):
 path=Path(path)
 if path.exists():raise DynamicError('history_bundle_exists','Immutable history cannot be replaced')
 contract=history_contract(runtime);history=runtime.run_history(scripts=source)
 records=history.get('execution_records',[])
 value={'version':'prepared-history-v1','contract':contract,'history':history,'synthetic':runtime.synthetic,
  'generation_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo_root(),text=True).strip(),
  'task_statuses':{c:history['actor_states']['Main'][i]['status'] for i,c in enumerate(history['tasks'])},
  'session_hashes':{a:[digest(x['session']) for x in states] for a,states in history['actor_states'].items()},
  'request_ledger_refs':[str(p.relative_to(path.parent)) for p in path.parent.glob('**/events.jsonl')],
  'accounting':{'generated_bundles':1,'task_attempts':len(records),'completed_histories':sum(x['status']=='completed_unjudged' for x in records),
   'failed_histories':sum(x['status']=='failed_history_retained' for x in records),'fixture_history_tasks':len(history['tasks']) if not records else 0,
   'real_history_task_attempts':len(records) if not runtime.synthetic else 0,'mock_environment_task_attempts':len(records) if runtime.synthetic else 0}}
 value['bundle_id']='history_bundle_'+digest(value);write_json(path,value)
 history['history_bundle_id']=value['bundle_id'];runtime.history=history
 return value
def load_history(runtime,path,*,reuse_journal=None):
 value=read_json(Path(path));content=copy.deepcopy(value);identity=content.pop('bundle_id',None)
 if value.get('version')!='prepared-history-v1' or identity!='history_bundle_'+digest(content):raise DynamicError('history_bundle_hash_mismatch','History bundle changed')
 if value['contract']!=history_contract(runtime):raise DynamicError('history_bundle_target_mismatch','Wrong model, tasks, assets or generation contract')
 if value['synthetic']!=runtime.synthetic:raise DynamicError('history_provenance_mismatch','Synthetic and real history cannot mix')
 h=copy.deepcopy(value['history'])
 if h['tasks']!=runtime.history_task_ids or h.get('environment_carry') is not False or set(h['actor_states'])!={'Main','A','B'}:raise DynamicError('history_scope_mismatch','Only complete actor-scoped sessions may carry')
 for actor,states in h['actor_states'].items():
  if len(states)!=2:raise DynamicError('history_session_incomplete',actor)
  for i,state in enumerate(states):
   session=state['session']
   if digest(session)!=state['snapshot_hash'] or digest(session)!=value['session_hashes'][actor][i] or session['config']['actor_id']!=actor or session['config']['task_id']!=h['tasks'][i]:raise DynamicError('history_session_hash_mismatch',actor)
 h['history_bundle_id']=identity;runtime.history=h
 if reuse_journal:append_jsonl(Path(reuse_journal),{'event':'history_bundle_loaded','bundle_id':identity,'target_block':runtime.block_id,'new_history_task_attempts':0})
 return h
def save_prefix(runtime,prefix,path):
 from trustfork.agents.pi_dynamic import ScriptSource
 path=Path(path)
 if path.exists():raise DynamicError('prefix_artifact_exists','Choose a new preparation attempt')
 if prefix['status']!='triggered':raise DynamicError('prefix_unavailable','Untriggered prefix cannot be used')
 source=prefix['scripts_after_prefix'];cursor={'kind':'scripted','remaining':{k:list(v) for k,v in source.scripts.items()}} if isinstance(source,ScriptSource) else {'kind':'provider','backend':runtime.execution_mode}
 value={'version':'prepared-prefix-v1','checkpoint':prefix['checkpoint'],'source_cursor':cursor,'synthetic':runtime.synthetic}
 value['artifact_hash']=digest(value);write_json(path,value);return value
def load_prefix(runtime,path):
 from trustfork.agents.pi_dynamic import ScriptSource,ProviderSource
 value=read_json(Path(path));content=copy.deepcopy(value);expected=content.pop('artifact_hash',None)
 if value.get('version')!='prepared-prefix-v1' or digest(content)!=expected:raise DynamicError('prefix_artifact_hash_mismatch','Prefix file changed')
 validate_checkpoint(value['checkpoint']);runtime.validate_prefix_target(value['checkpoint'])
 if value['synthetic']!=runtime.synthetic:raise DynamicError('prefix_provenance_mismatch','No real/synthetic mixing')
 c=value['source_cursor']
 if c['kind']=='scripted':
  if runtime.execution_mode!='scripted-test':raise DynamicError('prefix_source_mismatch','Script cursor requires fixture backend')
  source=ScriptSource(c['remaining'])
 else:
  if c.get('backend')!=runtime.execution_mode:raise DynamicError('prefix_source_mismatch','Wrong provider backend')
  source=ProviderSource()
 return {'status':'triggered','checkpoint':value['checkpoint'],'scripts_after_prefix':source}
