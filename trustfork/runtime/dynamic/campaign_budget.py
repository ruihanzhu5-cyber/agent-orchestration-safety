"""Small durable CNY ledger and shared route rate windows; no credentials."""
from contextlib import contextmanager
from decimal import Decimal, ROUND_CEILING
import json
from pathlib import Path
import sqlite3
import time
from .common import DynamicError, canonical, digest

SCALE=1_000_000
def micro(value):
    d=Decimal(str(value))
    if not d.is_finite() or d<0:raise DynamicError('invalid_campaign_money','Finite nonnegative CNY required')
    return int((d*SCALE).to_integral_value(rounding=ROUND_CEILING))

def price_cny(input_tokens,output_tokens,price,usd_to_cny):
    if any(type(x) is not int or x<0 for x in (input_tokens,output_tokens)):
        raise DynamicError('invalid_provider_usage','Nonnegative integer tokens required')
    for v in (price.get('input'),price.get('output'),usd_to_cny):
        if v is None or not Decimal(str(v)).is_finite() or Decimal(str(v))<=0:
            raise DynamicError('provider_price_unknown','Strict positive evidenced price/conversion upper bounds required')
    return (Decimal(input_tokens)*Decimal(str(price['input']))+
            Decimal(output_tokens)*Decimal(str(price['output'])))*Decimal(str(usd_to_cny))/Decimal(1_000_000)

class CampaignBudget:
    def __init__(self,path,*,campaign_id,total_cny=100,phase_limits=None,must_exist=False,segment_id=None,segment_cny=None,segment_identity=None):
        self.path=Path(path)
        if must_exist and not self.path.is_file():raise DynamicError('campaign_original_ledger_missing','Original ledger must exist; never create a fresh continuation ledger')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.segment_id=segment_id
        if segment_id is not None and (not isinstance(segment_id,str) or not segment_id or not isinstance(segment_identity,dict) or not segment_identity or segment_cny is None or not 0<micro(segment_cny)<=micro(20)):
            raise DynamicError('campaign_segment_policy_invalid','Explicit source identity and segment ceiling within CNY20 required')
        phases=phase_limits if phase_limits is not None else {'interface_probe':20}
        policy={'campaign_id':campaign_id,'total_micro_cny':micro(total_cny),
                'phase_limits':{k:micro(v) for k,v in phases.items()},'version':'campaign-cny-v1'}
        if not isinstance(campaign_id,str) or not campaign_id or policy['total_micro_cny']>micro(100):
            raise DynamicError('campaign_policy_invalid','Campaign identity and total <= CNY100 required')
        if policy['phase_limits'].get('interface_probe',micro(101))>micro(20):
            raise DynamicError('campaign_policy_invalid','Interface phase must be within CNY20')
        with self.tx() as db:
            if must_exist:
                if not db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='policy'").fetchone() or not db.execute('SELECT value FROM policy WHERE id=1').fetchone():
                    raise DynamicError('campaign_original_ledger_missing','Original policy is absent; refusing empty ledger')
            db.execute('CREATE TABLE IF NOT EXISTS policy (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS requests (request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, phase TEXT NOT NULL, status TEXT NOT NULL, reserved INTEGER NOT NULL, settled INTEGER, metadata TEXT NOT NULL, usage TEXT, submitted_at REAL, updated_at REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS rate_slots (request_id TEXT PRIMARY KEY, route TEXT NOT NULL, tokens INTEGER NOT NULL, at REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS paused_routes (route TEXT PRIMARY KEY, reason TEXT NOT NULL)')
            previous=db.execute('SELECT value FROM policy WHERE id=1').fetchone()
            if previous and json.loads(previous[0])!=policy:raise DynamicError('campaign_policy_mismatch','Cannot reset or change durable campaign ceilings')
            if not previous:db.execute('INSERT INTO policy VALUES (1,?)',(canonical(policy).decode(),))
            db.execute('CREATE TABLE IF NOT EXISTS segments (segment_id TEXT PRIMARY KEY, ceiling INTEGER NOT NULL, identity TEXT NOT NULL)')
            if segment_id is not None:
                identity=canonical(segment_identity).decode()
                previous_segment=db.execute('SELECT ceiling,identity FROM segments WHERE segment_id=?',(segment_id,)).fetchone()
                if previous_segment and tuple(previous_segment)!=(micro(segment_cny),identity):raise DynamicError('campaign_segment_identity_mismatch','Cannot reset segment ceiling or source identity')
                if not previous_segment:db.execute('INSERT INTO segments VALUES (?,?,?)',(segment_id,micro(segment_cny),identity))
        self.policy=policy

    @contextmanager
    def tx(self):
        db=sqlite3.connect(self.path,timeout=30,isolation_level=None)
        db.row_factory=sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.execute('COMMIT')
        except BaseException:
            if db.in_transaction:db.execute('ROLLBACK')
            raise
        finally:db.close()

    def reserve(self,request_id,*,phase,reserved_cost_cny,metadata):
        metadata=dict(metadata)
        if self.segment_id is not None:metadata['segment_id']=self.segment_id
        amount=micro(reserved_cost_cny)
        if amount<=0:raise DynamicError('provider_price_unknown','Zero production reservations forbidden')
        fingerprint=digest({'phase':phase,'amount':amount,'metadata':metadata})
        with self.tx() as db:
            old=db.execute('SELECT * FROM requests WHERE request_id=?',(request_id,)).fetchone()
            if old:
                if old['fingerprint']!=fingerprint:raise DynamicError('campaign_request_identity_mismatch',request_id)
                return dict(old)
            if metadata.get('model_generation_group_id') is not None:
                owner=metadata.get('execution_attempt_id')
                if not owner:raise DynamicError('model_generation_identity_required','Fixed preparation must bind an execution attempt')
                owners={json.loads(r['metadata']).get('execution_attempt_id') for r in db.execute('SELECT metadata,status FROM requests') if r['status']!='cancelled_before_send' and json.loads(r['metadata']).get('model_generation_group_id')==metadata['model_generation_group_id']}
                if owners-{owner}:raise DynamicError('fixed_generation_already_started','This fixed history/prefix/branch already submitted in another attempt; reuse compatible artifacts or reconcile, never resample')
            if metadata.get('validation_group_id') is not None:
                limit=metadata.get('group_request_limit')
                if type(limit) is not int or not 0<limit<=24:raise DynamicError('validation_request_policy_invalid','Formal acceptance group limit must be within 24')
                used=sum(json.loads(r['metadata']).get('validation_group_id')==metadata['validation_group_id'] and r['status']!='cancelled_before_send' for r in db.execute('SELECT metadata,status FROM requests'))
                if used>=limit:raise DynamicError('validation_request_budget_exhausted','Formal group request limit reached; unknown submissions count')
            charged="CASE WHEN status='settled' THEN settled WHEN status='cancelled_before_send' THEN 0 ELSE reserved END"
            total=db.execute('SELECT COALESCE(SUM('+charged+'),0) FROM requests').fetchone()[0]
            phase_total=db.execute('SELECT COALESCE(SUM('+charged+'),0) FROM requests WHERE phase=?',(phase,)).fetchone()[0]
            if metadata.get('role_cost_ceiling_cny') is not None:
                role_total=sum((r['settled'] if r['status']=='settled' else 0 if r['status']=='cancelled_before_send' else r['reserved'])
                    for r in db.execute('SELECT * FROM requests') if json.loads(r['metadata']).get('kind')==metadata.get('kind'))
                if role_total+amount>micro(metadata['role_cost_ceiling_cny']):
                    raise DynamicError('provider_cost_budget_exhausted','Persistent role cost ceiling reached')
            if total+amount>self.policy['total_micro_cny']:raise DynamicError('campaign_cost_exhausted','CNY total reservation would exceed ceiling')
            if self.segment_id is not None:
                limit=db.execute('SELECT ceiling FROM segments WHERE segment_id=?',(self.segment_id,)).fetchone()[0]
                used=sum(r['settled'] if r['status']=='settled' else 0 if r['status']=='cancelled_before_send' else r['reserved']
                    for r in db.execute('SELECT * FROM requests') if json.loads(r['metadata']).get('segment_id')==self.segment_id)
                if used+amount>limit:raise DynamicError('campaign_segment_cost_exhausted','New segment reservations and settlements exceed its included ceiling')
            if phase in self.policy['phase_limits'] and phase_total+amount>self.policy['phase_limits'][phase]:
                raise DynamicError('campaign_phase_cost_exhausted','Phase is a subset of campaign total')
            db.execute('INSERT INTO requests VALUES (?,?,?,?,?,?,?,?,?,?)',
                (request_id,fingerprint,phase,'reserved',amount,None,canonical(metadata).decode(),None,None,time.time()))
            return dict(db.execute('SELECT * FROM requests WHERE request_id=?',(request_id,)).fetchone())

    def submitted(self,request_id):
        with self.tx() as db:
            row=db.execute('SELECT status FROM requests WHERE request_id=?',(request_id,)).fetchone()
            if not row or row[0]!='reserved':raise DynamicError('campaign_attempt_already_recorded','No automatic resend of durable request')
            db.execute("UPDATE requests SET status='submitted',submitted_at=?,updated_at=? WHERE request_id=?",(time.time(),time.time(),request_id))

    def settle(self,request_id,*,settled_cost_cny=None,usage=None,cancelled_before_send=False):
        with self.tx() as db:
            row=db.execute('SELECT * FROM requests WHERE request_id=?',(request_id,)).fetchone()
            if not row:raise DynamicError('campaign_request_missing',request_id)
            if cancelled_before_send:
                if row['status']!='reserved':raise DynamicError('campaign_cancel_after_send','Unknown charges cannot be cancelled')
                status='cancelled_before_send';amount=None
                db.execute('DELETE FROM rate_slots WHERE request_id=?',(request_id,))
            elif settled_cost_cny is None:
                if row['status'] not in ('submitted','charge_unknown'):raise DynamicError('campaign_settle_state',row['status'])
                status='charge_unknown';amount=None
            else:
                amount=micro(settled_cost_cny);status='settled'
                if row['status']=='settled':
                    if amount!=row['settled'] or canonical(usage).decode()!=row['usage']:raise DynamicError('campaign_settlement_mismatch',request_id)
                    return
                if row['status'] not in ('submitted','charge_unknown'):raise DynamicError('campaign_settle_state',row['status'])
                if amount>row['reserved']:raise DynamicError('campaign_price_bound_breached','Retain reservation; stop route and reconcile provider bill')
            db.execute('UPDATE requests SET status=?,settled=?,usage=?,updated_at=? WHERE request_id=?',
                (status,amount,canonical(usage).decode() if usage is not None else None,time.time(),request_id))

    def rate_wait(self,request_id,*,route,tokens,rpm,tpm,now=None):
        if any(type(x) is not int or x<=0 for x in (tokens,rpm,tpm)):raise DynamicError('invalid_rate_limits','Positive integer limits required')
        if tokens>tpm:raise DynamicError('request_exceeds_tpm','Single request cannot fit configured TPM')
        now=time.time() if now is None else now
        with self.tx() as db:
            pause=db.execute('SELECT reason FROM paused_routes WHERE route=?',(route,)).fetchone()
            if pause:raise DynamicError('provider_route_paused',pause[0])
            old=db.execute('SELECT route,tokens FROM rate_slots WHERE request_id=?',(request_id,)).fetchone()
            if old:
                if tuple(old)!=(route,tokens):raise DynamicError('rate_identity_mismatch',request_id)
                return 0
            slots=db.execute('SELECT at,tokens FROM rate_slots WHERE route=? AND at>? ORDER BY at',(route,now-60)).fetchall()
            if len(slots)<rpm and sum(x['tokens'] for x in slots)+tokens<=tpm:
                db.execute('INSERT INTO rate_slots VALUES (?,?,?,?)',(request_id,route,tokens,now));return 0
            return max(.01,60-(now-slots[0]['at']))

    def pause(self,route,reason):
        with self.tx() as db:db.execute('INSERT OR REPLACE INTO paused_routes VALUES (?,?)',(route,reason))

    def rows(self):
        with self.tx() as db:
            result=[]
            for row in db.execute('SELECT * FROM requests ORDER BY updated_at,request_id'):
                v=dict(row);v['metadata']=json.loads(v['metadata']);v['usage']=json.loads(v['usage']) if v['usage'] else None
                result.append(v)
            return result

    def summary(self):
        rows=self.rows()
        settled=sum(r['settled'] or 0 for r in rows if r['status']=='settled')
        pending=sum(r['reserved'] for r in rows if r['status'] in ('reserved','submitted','charge_unknown'))
        return {'campaign_id':self.policy['campaign_id'],'settled_cny':settled/SCALE,'unsettled_reserved_cny':pending/SCALE,
            'remaining_cny':(self.policy['total_micro_cny']-settled-pending)/SCALE,
            'submitted_attempts':sum(r['submitted_at'] is not None for r in rows),
            'status_counts':{s:sum(r['status']==s for r in rows) for s in sorted({r['status'] for r in rows})}}

    def segment_summary(self):
        if self.segment_id is None:return None
        rows=[r for r in self.rows() if r['metadata'].get('segment_id')==self.segment_id]
        with self.tx() as db:limit=db.execute('SELECT ceiling FROM segments WHERE segment_id=?',(self.segment_id,)).fetchone()[0]
        settled=sum(r['settled'] or 0 for r in rows if r['status']=='settled')
        pending=sum(r['reserved'] for r in rows if r['status'] in ('reserved','submitted','charge_unknown'))
        return {'segment_id':self.segment_id,'ceiling_cny':limit/SCALE,'settled_cny':settled/SCALE,'unsettled_reserved_cny':pending/SCALE,
            'remaining_cny':(limit-settled-pending)/SCALE,'submitted_attempts':sum(r['submitted_at'] is not None for r in rows)}
