"""Reconcile a retained deadline-ended history without repeating any generation."""
import hashlib,json,time
from pathlib import Path
from .common import DynamicError,digest,file_hash,read_json,write_json,canonical

def verify_deadline_task(root,task,requests):
 root=Path(root);record=task['record'];sessions=task['sessions']
 def require(condition,reason):
  if not condition:raise DynamicError('history_deadline_not_reconciled',reason)
 require(record['status']=='failed_history_retained' and record['termination_reason']=='pi_turn_effect_unknown' and record['budget']['remaining_seconds']==0,'Only the observed exhausted-deadline boundary may be reconciled')
 require(record['task_id']=='p007' and set(sessions)=={'Main','A','B'},'No missing actor or different task')
 for actor,snapshot in sessions.items():
  require(snapshot['config']['actor_id']==actor and snapshot['config']['task_id']=='p007' and digest(snapshot)==record['session_hashes'][actor],'Final actor-scoped snapshot/hash differs')
 part=read_json(root/'partial-state.json');transport=read_json(root/'control/transport-metrics.json')
 require(not part['errors'] and part.get('quiesce',{}).get('status')=='quiesced' and not part['quiesce']['active_at_deadline'] and not part['quiesce']['cancellations'],'Work operations are not proven quiescent')
 require(part.get('freeze',{}).get('status')=='frozen' and part.get('environment_export')==record['frozen_state'],'Complete frozen state differs')
 frozen=record['frozen_state'];require(frozen.get('status')=='frozen_export' and file_hash(Path(frozen['workspace_tar']))==frozen['sha256'],'Frozen workspace unavailable or changed')
 require(transport.get('bridge_exit_code')==0 and transport.get('transport_failure') is None and transport.get('reader_closed') is True and not transport.get('reader_alive') and not transport.get('processor_alive'),'Bridge not completely closed/drained')
 require(transport['accepted_bytes']==transport['persisted_bytes']==transport['processed_bytes']==(root/'control/rpc-inbound.spool').stat().st_size and transport['unpersisted_tail_bytes']==transport['unprocessed_tail_bytes']==0,'Unprocessed or unpersisted RPC tail remains')
 guards=[json.loads(line) for line in (root/'control/network-guard.jsonl').open() if line.strip()]
 require(not any(any(v['guard'].get(k) for k in ('network_attempts','blocked_host_fs','blocked_host_exec')) for v in guards),'Isolation guard violation')
 require({v.get('actor_id') for v in guards if v['operation']=='close'}=={'Main','A','B'},'Final closed actors missing')
 unknown=[]
 require(bool(requests),'No actual preparation request evidence')
 for row in requests:
  require(row['status'] in ('settled','charge_unknown'),'A request is still live/reserved')
  if row['status']=='charge_unknown':
   m=json.loads(row['metadata']) if isinstance(row['metadata'],str) else row['metadata'];actor=m['actor_id'];last=next((v for v in reversed(sessions[actor]['messages']) if v['role']=='assistant'),{})
   require(last.get('stopReason')=='aborted' and row['request_id'] in {v['attempt_id'] for v in record['budget']['attempts'] if v['actor_id']==actor},'Unknown provider submission is not bound to a captured aborted final turn')
   unknown.append(row['request_id'])
 h=hashlib.sha256();h.update(b'[');stages=set();failed=False;frozen_event=False
 for i,line in enumerate((root/'events.jsonl').open()):
  value=json.loads(line)
  if i:h.update(b',')
  h.update(canonical(value))
  if value['event_type']=='model_request_ready':stages.add(value['stage_id'])
  if value['event_type']=='history_execution_failed':failed=value['payload'].get('code')=='pi_turn_effect_unknown'
  if value['event_type']=='abnormal_state_frozen':frozen_event=True
 h.update(b']')
 require(h.hexdigest()==record['request_ledger_hash'] and failed and frozen_event and {'fragment_1','fragment_2','fragment_3'}<=stages,'Incomplete source event ledger or unfinished earlier stages')
 hashes={str(p):file_hash(p) for p in (root/'task-completion.json',root/'history-execution.json',root/'partial-state.json',root/'control/transport-metrics.json',root/'control/network-guard.jsonl',root/'events.jsonl')}
 return {'version':'retained-history-deadline-reconciliation-v1','effective_history_status':'budget_ended','original_status':record['status'],'original_termination_reason':record['termination_reason'],'final_snapshots_complete':True,'earlier_partial_snapshot_statuses':{k:v['status'] for k,v in part['sessions'].items()},'final_bridge_drained_and_closed':True,'work_quiesced_and_frozen':True,'unknown_provider_requests_retained':unknown,'new_model_requests':0,'task_success_claimed':False,'source_hashes':hashes}

def inspect_retained_deadline(budget,config,parent_attempt):
 from .history import History
 from .prepared_artifacts import history_contract
 from .provider import ProviderTransport
 from trustfork.agents.pi_dynamic import PiDynamic
 with budget.tx() as db:
  first=db.execute('SELECT * FROM execution_stages WHERE attempt_id=? AND stage_id=?',(parent_attempt,'history/H1')).fetchone()
  second=db.execute('SELECT * FROM execution_stages WHERE attempt_id=? AND stage_id=?',(parent_attempt,'history/H2')).fetchone()
  if not first or not second or first['state']!='completed' or second['state']!='failed' or not second['result']:raise DynamicError('history_deadline_not_reconciled','Require original completed H1 and retained failed H2')
  saved=[dict(first),dict(second)]
  requests=[dict(v) for v in db.execute('SELECT * FROM requests') if json.loads(v['metadata']).get('execution_attempt_id')==parent_attempt and json.loads(v['metadata']).get('execution_stage_id')=='history/H2']
 for row in saved:
  for name,hashed in json.loads(row['artifacts']).items():
   if file_hash(Path(name))!=hashed:raise DynamicError('execution_stage_artifact_changed','Original retained history artifact changed')
 h1=read_json(Path(json.loads(saved[0]['result'])['path']));path=Path(json.loads(saved[1]['result'])['path']);task=read_json(path)
 proof=verify_deadline_task(path.parent,task,requests);proof['source_attempt']=parent_attempt
 history=History();history.add_task('p002',h1['sessions'],synthetic=h1['record']['synthetic'],status=h1['record']['status'])
 t=ProviderTransport(config,mode='api' if not task['record']['synthetic'] else 'mock',journal=path.parent/'unused-read-only-preflight.jsonl',authorize_real=not task['record']['synthetic'],max_requests=1)
 runtime=PiDynamic('p007',path.parent/'unused-read-only-preflight',provider=t,team_model='deepseekflash',protocol='F',history_task=True)
 identity={'contract':history_contract(runtime),'previous_history_hash':digest(history.export())}
 if digest(identity)!=saved[1]['identity_hash']:raise DynamicError('history_deadline_not_reconciled','Current exact history generation contract differs; do not re-label compatibility')
 return {'task':task,'proof':proof,'old_stage':saved[1],'stage_identity':identity}

def register_deadline_carry(attempt,retained):
 proof=retained['proof'];task=retained['task'];out=attempt.path/'reconciliation';out.mkdir(parents=True,exist_ok=True)
 record={**task['record'],'status':'budget_ended','termination_reason':'time_limit','deadline_reconciliation':proof};record.pop('history_id',None);record['history_id']='history_'+digest(record)
 target=out/'task-completion.json';write_json(out/'history-execution.json',record);write_json(out/'evidence.json',proof)
 write_json(target,{**task,'record':record,'execution_attempt_id':attempt.attempt_id,'source_execution_attempt_id':proof['source_attempt'],'source_artifacts_unchanged':True})
 old=retained['old_stage']
 with attempt.budget.tx() as db:
  if db.execute('SELECT 1 FROM execution_stages WHERE attempt_id=? AND stage_id=?',(attempt.attempt_id,'history/H2')).fetchone():raise DynamicError('history_deadline_already_registered','Use the existing guarded stage; do not overwrite')
  db.execute('INSERT INTO execution_stages VALUES (?,?,?,?,?,?,?,?)',(attempt.attempt_id,'history/H2',old['identity_hash'],'failed',old['result'],old['artifacts'],old['error'],time.time()))
  attempt._transition(db,'history/H2','retained_failed_parent_for_reconciliation',{'source_attempt':proof['source_attempt'],'source_hashes':proof['source_hashes']})
 return attempt.reconcile('history/H2',retained['stage_identity'],lambda:{'path':str(target),'task_id':'p007','status':'budget_ended','source_attempt':proof['source_attempt'],'new_model_requests':0},artifacts=lambda v:[target,out/'history-execution.json',out/'evidence.json'])
