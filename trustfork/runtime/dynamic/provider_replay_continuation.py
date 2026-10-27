"""One explicitly traced retry for a deterministic pre-HTTP Pi replay-guard defect."""
import json
from pathlib import Path
from .common import DynamicError,read_json,file_hash
ERROR='Incomplete private reasoning replay'

def verified_replay_parent(budget,source_attempt):
 with budget.tx() as db:
  prefix=db.execute('SELECT * FROM execution_stages WHERE attempt_id=? AND stage_id=?',(source_attempt,'prefix/S')).fetchone()
  failed=db.execute('SELECT * FROM execution_stages WHERE attempt_id=? AND stage_id=?',(source_attempt,'t3/S/HP')).fetchone()
  if not prefix or prefix['state']!='completed' or not failed or failed['state']!='failed' or not failed['error']:raise DynamicError('replay_continuation_not_verified','Require completed S checkpoint and the retained failed first HP attempt')
  error=json.loads(failed['error'])
  if error.get('code')!='pi_generation_failed' or ERROR not in error.get('reason',''):raise DynamicError('replay_continuation_not_verified','No task/goal/refusal outcome may trigger this repair')
  for p,h in json.loads(prefix['artifacts']).items():
   if file_hash(Path(p))!=h:raise DynamicError('replay_source_changed','Original completed S prefix changed')
  path=Path(json.loads(prefix['result'])['path']);root=path.parent;run_path=root/'HP/attempt-0/run.json';run=read_json(run_path)
  if run['run_status'] in ('valid_behavior','resource_ended'):raise DynamicError('replay_valid_behavior_forbidden','Never resample a valid or resource-ended research outcome')
  requests=[dict(v) for v in db.execute('SELECT * FROM requests') if json.loads(v['metadata']).get('execution_attempt_id')==source_attempt and json.loads(v['metadata']).get('execution_stage_id')=='t3/S/HP']
  if not requests or any(v['status']!='settled' for v in requests):raise DynamicError('replay_unknown_request_forbidden','Original HP requests must all be settled, not blindly replayed')
  submitted={v['request_id'] for v in requests};blocked=[]
  for line in (run_path.parent/'events.jsonl').open():
   e=json.loads(line)
   if e['event_type']=='model_response' and ERROR in (e['payload'].get('response') or {}).get('errorMessage',''):blocked.append(e['request_id'])
  if not blocked or any(v in submitted for v in blocked):raise DynamicError('replay_continuation_not_verified','Guard failure must be proven before its own HTTP submission')
  for row in db.execute('SELECT identity FROM execution_attempts'):
   if (json.loads(row['identity']).get('provider_replay_continuation') or {}).get('source_attempt')==source_attempt:raise DynamicError('replay_continuation_limit','Only one traced repair of this infrastructure attempt')
 history=root.parent.parent/'history/history-bundle.json'
 return {'version':'pi-native-replay-guard-continuation-v1','source_attempt':source_attempt,'source_error':error,'failed_run':str(run_path),'failed_run_hash':file_hash(run_path),'failed_events_hash':file_hash(run_path.parent/'events.jsonl'),'blocked_before_http':blocked,'source_prefix':str(path),'source_prefix_hash':file_hash(path),'history_bundle':str(history),'history_bundle_hash':file_hash(history),'retained_failed_attempt_is_not_a_valid_primary_sample':True,'retry_basis':'Deterministic interface guard error only; no outcome-based selection; repeat HP from the unchanged saved prefix, not from a fabricated mid-branch checkpoint'}
