"""Invocation identity is independent of wording, acknowledgments and messages."""
import copy
import uuid
import threading
from functools import wraps
from .common import DynamicError


def _locked(method):
    @wraps(method)
    def call(self,*args,**kwargs):
        with self.lock:return method(self,*args,**kwargs)
    return call


class Delegations:
    def __init__(self, ledger, membership):
        self.ledger, self.membership, self.rows = ledger, membership, []
        self.lock=threading.RLock()

    @_locked
    def prepare(self, actor, task_text, *, source='main_voluntary', context_refs=None, epoch=0, request_id=None, stage_id='initial'):
        if actor not in 'ABCD' or len(actor) != 1 or not self.membership.admitted(actor):
            raise DynamicError('delegation_member_unavailable', actor)
        if not isinstance(task_text, str) or not task_text.strip():
            raise DynamicError('empty_delegation', actor)
        row = {'delegation_id':uuid.uuid4().hex, 'invocation_id':uuid.uuid4().hex, 'actor_id':actor,
               'task_text':task_text, 'context_refs':context_refs or [], 'source':source, 'stage_epoch':epoch,
               'status':'queued', 'release_version':None, 'terminal_status':None,'request_id':request_id,
               'version':1,'stage_id':stage_id}
        event = self.ledger.append('delegation_prepared', copy.deepcopy(row), actor_id='Main', stage_epoch=epoch,stage_id=stage_id,
            invocation_id=row['invocation_id'],request_id=request_id)
        row['created_event_id'] = event['event_id']
        self.rows.append(row)
        return copy.deepcopy(row)

    @_locked
    def get(self, delegation_id):
        row = next((x for x in self.rows if x['delegation_id'] == delegation_id), None)
        if row is None:
            raise DynamicError('delegation_not_found', delegation_id)
        return row

    def _record_change(self,row,event_type,*,stage_id=None,epoch=None,request_id=None,**extra):
        row['version']=row.get('version',1)+1
        return self.ledger.append(event_type,{**copy.deepcopy(row),**extra},actor_id='Main',
            stage_id=stage_id or row.get('stage_id','initial'),stage_epoch=row['stage_epoch'] if epoch is None else epoch,
            request_id=request_id,invocation_id=row['invocation_id'])

    @_locked
    def update(self, delegation_id, task_text, *, stage_id=None, epoch=None, request_id=None):
        row = self.get(delegation_id)
        if row['source']=='runtime_startup':raise DynamicError('startup_contract_active',delegation_id)
        if row['status'] != 'queued' or not task_text.strip():
            raise DynamicError('delegation_not_editable', delegation_id)
        previous=row['task_text'];row['task_text'] = task_text
        self._record_change(row,'delegation_updated',stage_id=stage_id,epoch=epoch,request_id=request_id,previous_task_text=previous)
        return copy.deepcopy(row)

    @_locked
    def cancel(self, delegation_id, *, stage_id=None, epoch=None, request_id=None):
        row = self.get(delegation_id)
        if row['source']=='runtime_startup':raise DynamicError('startup_contract_active',delegation_id)
        if row['status'] not in ('queued', 'released'):
            raise DynamicError('delegation_not_cancellable', delegation_id)
        row.update(status='terminal', terminal_status='cancelled')
        self._record_change(row,'delegation_cancelled',stage_id=stage_id,epoch=epoch,request_id=request_id)
        return copy.deepcopy(row)

    @_locked
    def start(self,delegation_id,*,stage_id,epoch):
        row=self.get(delegation_id)
        if row['status']!='released':raise DynamicError('delegation_not_released',delegation_id)
        row['status']='started'
        self._record_change(row,'delegation_started',stage_id=stage_id,epoch=epoch)
        return row

    def complete(self,invocation_id,*,stage_id,epoch,request_id,terminal_status='completed'):
        with self.lock:
            row=next((x for x in self.rows if x['invocation_id']==invocation_id),None)
            if row is None:raise DynamicError('invocation_not_found',invocation_id)
            if row['status']=='terminal':return copy.deepcopy(row)
            row.update(status='terminal',terminal_status=terminal_status)
            self._record_change(row,'delegation_completed',stage_id=stage_id,epoch=epoch,request_id=request_id)
            return copy.deepcopy(row)

    @_locked
    def release(self, *, epoch,stage_id=None,request_id=None):
        released = []
        for row in self.rows:
            if row['status'] == 'queued' and row['stage_epoch'] == epoch and self.membership.admitted(row['actor_id']):
                row.update(status='released', release_version=self.membership.version)
                self._record_change(row,'delegation_released',stage_id=stage_id,epoch=epoch,request_id=request_id)
                released.append(copy.deepcopy(row))
        return released

    @_locked
    def stage_transition(self, epoch, *, new_session):
        for row in self.rows:
            if row['stage_epoch'] == epoch and row['status'] != 'terminal':
                if new_session:
                    row.update(status='terminal', terminal_status='cancelled_new_session')
                elif row['status'] == 'queued':
                    row.update(stage_epoch=epoch + 1, carried_from_epoch=epoch)
                else:
                    # The stage barrier has drained the current full batch. An
                    # unfinished old invocation is terminal, never resumed in a
                    # later stage; only work that was still queued may migrate.
                    row.update(status='terminal',terminal_status='cancelled_stage_boundary')
                row['version']=row.get('version',1)+1
                self.ledger.append('delegation_stage_transition',copy.deepcopy(row),actor_id=row['actor_id'],
                    stage_id=row.get('stage_id','initial'),stage_epoch=epoch,invocation_id=row['invocation_id'])
