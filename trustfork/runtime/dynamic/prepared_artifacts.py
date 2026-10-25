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
  'execution_backend':runtime.execution_mode,'team_binding_hash':binding_hash(runtime),'source_asset_hashes':{c:load_case(c)['deployed_asset_hash'] for c in runtime.history_task_ids},
  'generation_config_hash':digest({'normal_goal':__import__('trustfork.runtime.dynamic.goals',fromlist=['NORMAL_GOAL']).NORMAL_GOAL,
   'budget':[120,48000,4096,1200],'temperature':0.2,'controller':file_hash(repo_root()/'trustfork/agents/pi_dynamic.py'),
   'history_executor':file_hash(repo_root()/'trustfork/runtime/dynamic/history_execution.py')})}
def prepare_history(runtime,source,path):
 path=Path(path)
 if path.exists():raise DynamicError('history_bundle_exists','Immutable history cannot be replaced')
 contract=history_contract(runtime)
 journal=runtime.provider.journal if runtime.provider is not None else None
 journal_start=journal.stat().st_size if journal is not None and journal.exists() else 0
 try:history=runtime.run_history(scripts=source)
 except (DynamicError,OSError) as error:
  write_json(path.with_suffix('.blocked.json'),{'version':'prepared-history-blocked-v1','contract':contract,'status':'blocked','reason':getattr(error,'code',type(error).__name__),'task_attempt_directories':[p.name for p in (path.parent/'history').glob('*') if (p/'events.jsonl').exists()],'synthetic':runtime.synthetic})
  raise
 records=history.get('execution_records',[])
 value={'version':'prepared-history-v2','contract':contract,'history':copy.deepcopy(history),'synthetic':runtime.synthetic,
  'generation_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo_root(),text=True).strip(),
  'task_statuses':{c:history['actor_states']['Main'][i]['status'] for i,c in enumerate(history['tasks'])},
  'session_hashes':{a:[digest(x['session']) for x in states] for a,states in history['actor_states'].items()},
  'request_ledger_refs':[str(p.relative_to(path.parent)) for p in path.parent.glob('**/events.jsonl')],
  'accounting':{'generated_bundles':1,'task_attempts':len(records),'completed_histories':sum(x['status']=='completed_unjudged' for x in records),
   'failed_histories':sum(x['status']=='failed_history_retained' for x in records),'fixture_history_tasks':len(history['tasks']) if not records else 0,
   'real_history_task_attempts':len(records) if not runtime.synthetic else 0,'mock_environment_task_attempts':len(records) if runtime.synthetic else 0}}
 import hashlib,os
 files=set(path.parent.glob('**/events.jsonl'))|set(path.parent.glob('**/network-guard.jsonl'))
 if runtime.provider is not None and runtime.provider.journal.exists():files.add(runtime.provider.journal)
 value['request_ledger_prefixes']=[{'path':os.path.relpath(p,path.parent),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(files)]
 from trustfork.tools.audit_model_calls import audit_request_events
 import json
 audits=[audit_request_events([json.loads(line) for line in p.read_text().splitlines()]) for p in path.parent.glob('**/events.jsonl')]
 value['accounting']['actual_provider_calls']={'real':sum(a['real_model_calls_in_observed_scope'] or 0 for a in audits),'submitted':sum(len(a['request_records']) for a in audits),'source':'actual bridge request submissions; no summary constants'}
 if journal is not None and journal.exists():
  with journal.open('rb') as stream:stream.seek(journal_start);submitted=[json.loads(line) for line in stream.read().splitlines() if line.strip()]
  submitted=[r for r in submitted if r.get('status')=='submitted']
 else:submitted=[]
 unresolved=any(r.get('source') not in ('api','mock') for r in submitted)
 value['accounting']['actual_provider_calls']={'version':'transport-interval-v1','real':None if unresolved else sum(r['source']=='api' for r in submitted),'mock':sum(r.get('source')=='mock' for r in submitted),'submitted':len(submitted),'journal_byte_start':journal_start,'journal_byte_end':journal.stat().st_size if journal is not None and journal.exists() else 0,'source':'actual transport submitted records in this history preparation interval'}
 value['bundle_id']='history_bundle_'+digest(value);write_json(path,value)
 history['history_bundle_id']=value['bundle_id'];runtime.history=history
 return value
def load_history(runtime,path,*,reuse_journal=None):
 value=read_json(Path(path));content=copy.deepcopy(value);identity=content.pop('bundle_id',None)
 if value.get('version')!='prepared-history-v2' or identity!='history_bundle_'+digest(content):raise DynamicError('history_bundle_hash_mismatch','History bundle changed')
 if value['contract']!=history_contract(runtime):raise DynamicError('history_bundle_target_mismatch','Wrong model, tasks, assets or generation contract')
 if value['synthetic']!=runtime.synthetic:raise DynamicError('history_provenance_mismatch','Synthetic and real history cannot mix')
 import hashlib
 for ref in value.get('request_ledger_prefixes',[]):
  log=(Path(path).parent/ref['path']).resolve()
  try:
   with log.open('rb') as stream:data=stream.read(ref['bytes'])
  except OSError:raise DynamicError('history_ledger_unavailable','Retained request evidence missing') from None
  if len(data)!=ref['bytes'] or hashlib.sha256(data).hexdigest()!=ref['sha256']:raise DynamicError('history_ledger_prefix_changed','Original request evidence changed')
 h=copy.deepcopy(value['history'])
 if h['tasks']!=runtime.history_task_ids or h.get('environment_carry') is not False or set(h['actor_states'])!={'Main','A','B'}:raise DynamicError('history_scope_mismatch','Only complete actor-scoped sessions may carry')
 for actor,states in h['actor_states'].items():
  if len(states)!=2:raise DynamicError('history_session_incomplete',actor)
  for i,state in enumerate(states):
   session=state['session']
   if digest(session)!=state['snapshot_hash'] or digest(session)!=value['session_hashes'][actor][i] or session['config']['actor_id']!=actor or session['config']['task_id']!=h['tasks'][i]:raise DynamicError('history_session_hash_mismatch',actor)
 h['history_bundle_id']=identity;runtime.history=h
 append_jsonl(Path(reuse_journal) if reuse_journal is not None else runtime.out/'history-bundle-reuse.jsonl',{'event':'history_bundle_loaded','bundle_id':identity,'target_block':runtime.block_id,'new_history_task_attempts':0})
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
