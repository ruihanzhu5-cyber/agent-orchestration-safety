"""Explicit user-authorized amendment of the original round's segment ceiling."""
import json,sqlite3,time
from pathlib import Path
from .common import DynamicError,digest,file_hash,canonical
from .campaign_budget import micro
ROUND='small-api-collection-20261027'
SEGMENT='plan-judge-followup-20261026'

def authorized_segment_ceiling(db,segment_id,ceiling):
 if ceiling==micro(20):return True
 if segment_id!=SEGMENT or not db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='small_api_budget_amendments'").fetchone():return False
 row=db.execute('SELECT old_ceiling,new_ceiling,baseline_segment_charged,max_new,max_judge,authorization,authorization_hash FROM small_api_budget_amendments WHERE round_id=? AND segment_id=?',(ROUND,SEGMENT)).fetchone()
 if not row:return False
 auth=json.loads(row[5])
 base_valid=row[0]==micro(20) and row[1]==row[2]+row[3] and row[3]==micro(50) and row[4]==micro(10) and digest(auth)==row[6] and auth.get('max_new_cny')==50 and auth.get('max_judge_cny')==10 and auth.get('original_campaign_cny')==100
 if not base_valid:return False
 if ceiling==row[1]:return True
 extra=judge_followup_authorization(db)
 return extra is not None and extra['previous_ceiling']==row[1] and ceiling==extra['new_ceiling']

def amend_original_segment(path,baseline,*,backup):
 path,backup=Path(path),Path(backup)
 auth={'round_id':ROUND,'authorized_by':'user','date_asia_shanghai':'2026-10-27','max_new_cny':50,'max_judge_cny':10,'original_campaign_cny':100,'source':'User explicitly confirmed: 本轮新增最多50元，其中Judge最多10元，原100元总上限不变','baseline_requests_hash':digest(baseline['requests_before'])}
 expected={v['request_id']:v for v in baseline['requests_before']}
 old_segment=next(v for v in baseline['segments_before'] if v['segment_id']==SEGMENT)
 baseline_segment=sum((v['settled'] or 0) if v['status']=='settled' else 0 if v['status']=='cancelled_before_send' else v['reserved'] for v in expected.values() if json.loads(v['metadata']).get('segment_id')==SEGMENT)
 baseline_total=sum((v['settled'] or 0) if v['status']=='settled' else 0 if v['status']=='cancelled_before_send' else v['reserved'] for v in expected.values())
 target=baseline_segment+micro(50)
 if old_segment['ceiling']!=micro(20) or baseline_total+micro(50)>micro(100):raise DynamicError('small_api_budget_authorization_invalid','Original100 and retained baseline must bound the complete new round')
 with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as source:
  source.row_factory=sqlite3.Row
  if source.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='small_api_budget_amendments'").fetchone():
   row=source.execute('SELECT authorization_hash FROM small_api_budget_amendments WHERE round_id=?',(ROUND,)).fetchone()
   if row:
    actual=source.execute('SELECT ceiling FROM segments WHERE segment_id=?',(SEGMENT,)).fetchone()[0]
    if row[0]!=digest(auth) or not authorized_segment_ceiling(source,SEGMENT,actual):raise DynamicError('small_api_budget_amendment_mismatch','Never overwrite a different prior authorization')
    return {'status':'already_applied','segment_ceiling_cny':actual/1e6,'max_new_cny':50,'max_judge_cny':10,'authorization_hash':digest(auth)}
  if backup.exists():raise DynamicError('budget_backup_exists','Reconcile existing backup; never overwrite')
  backup.parent.mkdir(parents=True,exist_ok=True)
  with sqlite3.connect(backup) as dest:source.backup(dest)
 db=sqlite3.connect(path,isolation_level=None);db.row_factory=sqlite3.Row
 try:
  db.execute('PRAGMA synchronous=FULL');db.execute('BEGIN IMMEDIATE')
  policy=json.loads(db.execute('SELECT value FROM policy WHERE id=1').fetchone()[0])
  if policy['campaign_id']!='first-api-20261026' or policy['total_micro_cny']!=micro(100):raise DynamicError('small_api_budget_authorization_invalid','Original campaign must remain CNY100')
  current={v['request_id']:dict(v) for v in db.execute('SELECT * FROM requests')}
  if any(current.get(k)!=v for k,v in expected.items()):raise DynamicError('budget_original_fees_changed','Retained baseline request rows differ')
  segment=dict(db.execute('SELECT * FROM segments WHERE segment_id=?',(SEGMENT,)).fetchone())
  if segment!=old_segment:raise DynamicError('budget_original_segment_changed','Inspect any concurrent segment change')
  db.execute('CREATE TABLE small_api_budget_amendments (round_id TEXT PRIMARY KEY,segment_id TEXT NOT NULL,old_ceiling INTEGER NOT NULL,new_ceiling INTEGER NOT NULL,baseline_segment_charged INTEGER NOT NULL,baseline_campaign_charged INTEGER NOT NULL,max_new INTEGER NOT NULL,max_judge INTEGER NOT NULL,authorization TEXT NOT NULL,authorization_hash TEXT NOT NULL,at REAL NOT NULL)')
  db.execute('INSERT INTO small_api_budget_amendments VALUES (?,?,?,?,?,?,?,?,?,?,?)',(ROUND,SEGMENT,micro(20),target,baseline_segment,baseline_total,micro(50),micro(10),canonical(auth).decode(),digest(auth),time.time()))
  db.execute('UPDATE segments SET ceiling=? WHERE segment_id=?',(target,SEGMENT))
  if any(dict(db.execute('SELECT * FROM requests WHERE request_id=?',(k,)).fetchone())!=v for k,v in current.items()):raise DynamicError('budget_original_fees_changed','Authorization must not rewrite request or fee rows')
  db.execute('COMMIT')
 except BaseException:
  if db.in_transaction:db.execute('ROLLBACK')
  raise
 finally:db.close()
 return {'status':'applied','original_segment_ceiling_cny':20,'segment_ceiling_cny':target/1e6,'baseline_segment_charged_cny':baseline_segment/1e6,'baseline_campaign_charged_cny':baseline_total/1e6,'max_new_cny':50,'max_judge_cny':10,'original_campaign_cny':100,'authorization_hash':digest(auth),'backup_sha256':file_hash(backup),'all_existing_request_rows_unchanged':True}


JUDGE_FOLLOWUP_AUTH={'authorized_by':'user','date_asia_shanghai':'2026-10-27','max_round_new_cny':60,'max_judge_cny':10,'original_campaign_cny':100,'additional_scope':'Judge TH/TUL calibration and rescoring of existing frozen trajectories only; no team reruns','source':'User explicitly confirmed: 允许提高到60元，仅用于Judge补评'}

def judge_followup_authorization(db):
 if not db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='small_api_judge_followup_authorizations'").fetchone():return None
 row=db.execute('SELECT previous_ceiling,new_ceiling,authorization,authorization_hash FROM small_api_judge_followup_authorizations WHERE round_id=?',(ROUND,)).fetchone()
 if not row:return None
 auth=json.loads(row[2])
 if auth!=JUDGE_FOLLOWUP_AUTH or digest(auth)!=row[3] or row[1]!=row[0]+micro(10):return None
 return {'previous_ceiling':row[0],'new_ceiling':row[1],'authorization':auth,'authorization_hash':row[3]}

def amend_judge_followup(path,*,backup):
 """Append the second explicit authorization; never rewrite old fees or first authorization."""
 path,backup=Path(path),Path(backup)
 with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as source:
  previous=judge_followup_authorization(source)
  if previous:return {'status':'already_applied',**previous}
  old=source.execute('SELECT ceiling FROM segments WHERE segment_id=?',(SEGMENT,)).fetchone()[0]
  if not authorized_segment_ceiling(source,SEGMENT,old):raise DynamicError('budget_original_authorization_invalid',SEGMENT)
  if backup.exists():raise DynamicError('budget_backup_exists','Never overwrite backup')
  backup.parent.mkdir(parents=True,exist_ok=True)
  with sqlite3.connect(backup) as dest:source.backup(dest)
 with sqlite3.connect(path) as db:
  db.execute('BEGIN IMMEDIATE')
  before=list(db.execute('SELECT * FROM requests ORDER BY request_id'))
  if db.execute('SELECT ceiling FROM segments WHERE segment_id=?',(SEGMENT,)).fetchone()[0]!=old:raise DynamicError('budget_changed','Concurrent ceiling change')
  db.execute('CREATE TABLE small_api_judge_followup_authorizations (round_id TEXT PRIMARY KEY,previous_ceiling INTEGER NOT NULL,new_ceiling INTEGER NOT NULL,authorization TEXT NOT NULL,authorization_hash TEXT NOT NULL,at REAL NOT NULL)')
  db.execute('INSERT INTO small_api_judge_followup_authorizations VALUES (?,?,?,?,?,?)',(ROUND,old,old+micro(10),canonical(JUDGE_FOLLOWUP_AUTH).decode(),digest(JUDGE_FOLLOWUP_AUTH),time.time()))
  db.execute('UPDATE segments SET ceiling=? WHERE segment_id=?',(old+micro(10),SEGMENT))
  if list(db.execute('SELECT * FROM requests ORDER BY request_id'))!=before:raise DynamicError('budget_old_fees_changed','No old row may change')
 return {'status':'applied','previous_segment_ceiling_cny':old/1e6,'new_segment_ceiling_cny':(old+micro(10))/1e6,'round_new_cny':60,'judge_cny':10,'campaign_cny':100,'authorization_hash':digest(JUDGE_FOLLOWUP_AUTH),'all_old_requests_unchanged':True}
