"""Versioned execution attempts sharing immutable original campaign/segment money."""
import json,sqlite3,time,re
from pathlib import Path
from .common import DynamicError,canonical,digest,file_hash,read_json
from .artifacts import atomic_json
MIGRATION='runtime-review-attempts-v1'
TABLES=('policy','requests','segments','rate_slots','paused_routes')

def original_facts(db):
 return {name:[dict(row) for row in db.execute('SELECT * FROM '+name+' ORDER BY rowid')] for name in TABLES}

def migrate_attempts(path,*,apply=False,backup=None):
 path=Path(path)
 if not path.is_file():raise DynamicError('campaign_original_ledger_missing','Never create a replacement ledger')
 with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as source:
  source.row_factory=sqlite3.Row;before=original_facts(source)
  exists=bool(source.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='execution_attempts'").fetchone())
  policy=json.loads(before['policy'][0]['value'])
  if policy['campaign_id']!='first-api-20261026' or policy['total_micro_cny']!=100000000:raise DynamicError('execution_campaign_bucket_mismatch','Original CNY100 required')
  segment=next((r for r in before['segments'] if r['segment_id']=='plan-judge-followup-20261026'),None)
  from .small_api_budget import authorized_segment_ceiling
  if segment is None or not authorized_segment_ceiling(source,segment['segment_id'],segment['ceiling']):raise DynamicError('execution_segment_bucket_mismatch','Existing original segment or explicit user amendment required')
  result={'migration':MIGRATION,'needs_migration':not exists,'dry_run':not apply,'original_facts_hash':digest(before),'campaign_id':policy['campaign_id'],'segment_id':segment['segment_id'],'segment_identity':json.loads(segment['identity']),'segment_ceiling_micro_cny':segment['ceiling'],'request_rows':len(before['requests'])}
  if not apply:return result
  if backup is None:raise DynamicError('ledger_backup_required','Back up original ledger before transaction migration')
  backup=Path(backup);backup.parent.mkdir(parents=True,exist_ok=True)
  if backup.exists():raise DynamicError('ledger_backup_exists','Never overwrite a prior backup')
  with sqlite3.connect(backup) as target:source.backup(target)
 result['backup_sha256']=file_hash(backup)
 db=sqlite3.connect(path,isolation_level=None);db.row_factory=sqlite3.Row
 try:
  db.execute('PRAGMA synchronous=FULL');db.execute('BEGIN IMMEDIATE')
  current=original_facts(db)
  if digest(current)!=digest(before):raise DynamicError('ledger_changed_during_migration','Reconcile concurrent writers before migration')
  db.execute('CREATE TABLE IF NOT EXISTS execution_attempts (attempt_id TEXT PRIMARY KEY,parent_attempt TEXT NOT NULL,segment_id TEXT NOT NULL,identity TEXT NOT NULL,created_at REAL NOT NULL)')
  db.execute('CREATE TABLE IF NOT EXISTS execution_stages (attempt_id TEXT NOT NULL,stage_id TEXT NOT NULL,identity_hash TEXT NOT NULL,state TEXT NOT NULL,result TEXT,artifacts TEXT NOT NULL,error TEXT,updated_at REAL NOT NULL,PRIMARY KEY(attempt_id,stage_id))')
  db.execute('CREATE TABLE IF NOT EXISTS execution_transitions (sequence INTEGER PRIMARY KEY AUTOINCREMENT,attempt_id TEXT NOT NULL,stage_id TEXT NOT NULL,state TEXT NOT NULL,detail TEXT NOT NULL,at REAL NOT NULL)')
  if digest(original_facts(db))!=digest(before):raise DynamicError('ledger_migration_changed_facts','Rollback: old money/identities must not change')
  db.execute('COMMIT')
 except BaseException:
  if db.in_transaction:db.execute('ROLLBACK')
  raise
 finally:db.close()
 result.update(dry_run=False,applied=True,original_facts_unchanged=True)
 return result

class ExecutionAttempt:
 def __init__(self,budget,path,*,attempt_id,parent_attempt,identity):
  if not re.fullmatch('[A-Za-z0-9_-]{1,80}',attempt_id) or not parent_attempt or not identity:raise DynamicError('invalid_execution_attempt','Explicit safe attempt, parent and code/config identity required')
  if budget.segment_id!='plan-judge-followup-20261026':raise DynamicError('execution_segment_bucket_mismatch','Reuse the existing original segment')
  if set(identity)&{'version','parent_attempt','segment_id'}:raise DynamicError('execution_identity_reserved_fields','Parent and budget association cannot be overridden')
  self.budget,self.path,self.attempt_id=budget,Path(path),attempt_id
  self.identity={'version':MIGRATION,'parent_attempt':parent_attempt,'segment_id':budget.segment_id,**identity}
  meta={'attempt_id':attempt_id,'identity':self.identity}
  if (self.path/'execution-attempt.json').exists() and read_json(self.path/'execution-attempt.json')!=meta:raise DynamicError('execution_output_identity_mismatch','Never overwrite a different output')
  encoded=canonical(self.identity).decode()
  with budget.tx() as db:
   if not db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='execution_attempts'").fetchone():raise DynamicError('execution_migration_required','Dry-run, backup and apply association migration first')
   old=db.execute('SELECT * FROM execution_attempts WHERE attempt_id=?',(attempt_id,)).fetchone()
   if old and old['identity']!=encoded:raise DynamicError('execution_attempt_identity_mismatch','New code/config requires a new attempt; retain old attempts')
   if not old:db.execute('INSERT INTO execution_attempts VALUES (?,?,?,?,?)',(attempt_id,parent_attempt,budget.segment_id,encoded,time.time()))
  self.path.mkdir(parents=True,exist_ok=True)
  meta={'attempt_id':attempt_id,'identity':self.identity}
  if (self.path/'execution-attempt.json').exists() and read_json(self.path/'execution-attempt.json')!=meta:raise DynamicError('execution_output_identity_mismatch','Never overwrite a different output')
  atomic_json(self.path/'execution-attempt.json',meta)

 def reuse_parent_stage(self,stage,identity):
  """Inherit the recorded compatible occurrence, never select a better outcome."""
  hashed=digest(identity)
  with self.budget.tx() as db:
   if db.execute('SELECT 1 FROM execution_stages WHERE attempt_id=? AND stage_id=?',(self.attempt_id,stage)).fetchone():return False
   old=db.execute('SELECT * FROM execution_stages WHERE attempt_id=? AND stage_id=?',(self.identity['parent_attempt'],stage)).fetchone()
   if old is None or old['state']!='completed' or old['identity_hash']!=hashed:return False
   result=self._checked(old)
   db.execute('INSERT INTO execution_stages VALUES (?,?,?,?,?,?,?,?)',(self.attempt_id,stage,hashed,'completed',old['result'],old['artifacts'],None,time.time()))
   self._transition(db,stage,'inherited_compatible_parent',{'parent_attempt':self.identity['parent_attempt'],'identity_hash':hashed,'source_result_hash':digest(result)})
  return True

 def request_id(self,stage,suffix):return self.attempt_id+'.'+digest(stage)[:12]+'.'+suffix
 def _artifacts(self,paths):return {str(Path(p).resolve()):file_hash(Path(p)) for p in paths}
 def _checked(self,row):
  for name,hashed in json.loads(row['artifacts']).items():
   if not Path(name).is_file() or file_hash(Path(name))!=hashed:raise DynamicError('execution_stage_artifact_changed','Previously completed artifact changed: '+Path(name).name)
  return json.loads(row['result'])
 def _transition(self,db,stage,state,detail):db.execute('INSERT INTO execution_transitions(attempt_id,stage_id,state,detail,at) VALUES (?,?,?,?,?)',(self.attempt_id,stage,state,canonical(detail).decode(),time.time()))
 def run(self,stage,identity,fn,*,artifacts=lambda result:[]):
  hashed=digest(identity)
  with self.budget.tx() as db:
   row=db.execute('SELECT * FROM execution_stages WHERE attempt_id=? AND stage_id=?',(self.attempt_id,stage)).fetchone()
   if row:
    if row['identity_hash']!=hashed:raise DynamicError('execution_stage_identity_mismatch','Source/protocol/scorer changed')
    if row['state']=='completed' or row['result'] is not None:return self._checked(row)
    raise DynamicError('execution_stage_requires_reconciliation','Do not replay started, failed or blocked actions; inspect/reconcile or record a new attempt')
   db.execute('INSERT INTO execution_stages VALUES (?,?,?,?,?,?,?,?)',(self.attempt_id,stage,hashed,'started',None,'{}',None,time.time()))
   self._transition(db,stage,'started',identity)
  try:
   result=fn();files=self._artifacts(artifacts(result))
  except (DynamicError,OSError,TimeoutError) as error:
   with self.budget.tx() as db:
    record=error.record() if isinstance(error,DynamicError) else {'code':type(error).__name__,'reason':str(error)}
    db.execute('UPDATE execution_stages SET state=?,error=?,updated_at=? WHERE attempt_id=? AND stage_id=?',('failed',canonical(record).decode(),time.time(),self.attempt_id,stage));self._transition(db,stage,'failed',record)
   raise
  state=result.get('status','completed') if isinstance(result,dict) else 'completed'
  state='failed' if state in ('failed','failed_history_retained','infra_error','protocol_error') else state if state in ('blocked','not_started') else 'completed'
  with self.budget.tx() as db:
   db.execute('UPDATE execution_stages SET state=?,result=?,artifacts=?,updated_at=? WHERE attempt_id=? AND stage_id=?',(state,canonical(result).decode(),canonical(files).decode(),time.time(),self.attempt_id,stage));self._transition(db,stage,state,{'artifact_hashes':files})
  return result
 def reconcile(self,stage,identity,validator,*,artifacts=lambda result:[]):
  # Validator must establish the complete actual artifact contract, never infer it from HTTP200.
  result=validator();files=self._artifacts(artifacts(result))
  if not files:raise DynamicError('execution_reconcile_artifact_required','No complete checkpoint/history/run artifact supplied')
  with self.budget.tx() as db:
   row=db.execute('SELECT * FROM execution_stages WHERE attempt_id=? AND stage_id=?',(self.attempt_id,stage)).fetchone()
   if row is None or row['identity_hash']!=digest(identity):raise DynamicError('execution_stage_identity_mismatch','Cannot reconcile unknown/different stage')
   if row['state']=='completed':return self._checked(row)
   db.execute('UPDATE execution_stages SET state=?,result=?,artifacts=?,updated_at=? WHERE attempt_id=? AND stage_id=?',('completed',canonical(result).decode(),canonical(files).decode(),time.time(),self.attempt_id,stage));self._transition(db,stage,'reconciled_complete_artifact',{'previous_state':row['state'],'artifact_hashes':files,'reconciler_source_hash':file_hash(Path(__file__))})
  return result
 def inspect(self):
  with self.budget.tx() as db:
   stages=[dict(r) for r in db.execute('SELECT * FROM execution_stages WHERE attempt_id=? ORDER BY stage_id',(self.attempt_id,))]
   outstanding=[dict(r) for r in db.execute("SELECT * FROM requests WHERE status IN ('reserved','submitted','charge_unknown')") if json.loads(r['metadata']).get('execution_attempt_id')==self.attempt_id or r['request_id'].startswith(self.attempt_id+'.')]
  return {'attempt_id':self.attempt_id,'identity':self.identity,'stages':stages,'unknown_submitted_requests':outstanding,'campaign':self.budget.summary(),'segment':self.budget.segment_summary()}
