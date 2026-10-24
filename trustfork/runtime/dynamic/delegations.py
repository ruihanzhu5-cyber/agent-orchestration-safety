"""Invocation identity is independent of wording, acknowledgments and messages."""
import copy
import uuid
from .common import DynamicError


class Delegations:
    def __init__(self, ledger, membership):
        self.ledger, self.membership, self.rows = ledger, membership, []

    def prepare(self, actor, task_text, *, source='main_voluntary', context_refs=None, epoch=0, request_id=None):
        if actor not in 'ABCD' or len(actor) != 1 or not self.membership.admitted(actor):
            raise DynamicError('delegation_member_unavailable', actor)
        if not isinstance(task_text, str) or not task_text.strip():
            raise DynamicError('empty_delegation', actor)
        row = {'delegation_id':uuid.uuid4().hex, 'invocation_id':uuid.uuid4().hex, 'actor_id':actor,
               'task_text':task_text, 'context_refs':context_refs or [], 'source':source, 'stage_epoch':epoch,
               'status':'queued', 'release_version':None, 'terminal_status':None,'request_id':request_id}
        event = self.ledger.append('delegation_prepared', copy.deepcopy(row), actor_id='Main', stage_epoch=epoch,
            invocation_id=row['invocation_id'],request_id=request_id)
        row['created_event_id'] = event['event_id']
        self.rows.append(row)
        return copy.deepcopy(row)

    def get(self, delegation_id):
        row = next((x for x in self.rows if x['delegation_id'] == delegation_id), None)
        if row is None:
            raise DynamicError('delegation_not_found', delegation_id)
        return row

    def update(self, delegation_id, task_text):
        row = self.get(delegation_id)
        if row['status'] != 'queued' or not task_text.strip():
            raise DynamicError('delegation_not_editable', delegation_id)
        row['task_text'] = task_text
        return copy.deepcopy(row)

    def cancel(self, delegation_id):
        row = self.get(delegation_id)
        if row['status'] not in ('queued', 'released'):
            raise DynamicError('delegation_not_cancellable', delegation_id)
        row.update(status='terminal', terminal_status='cancelled')

    def release(self, *, epoch):
        released = []
        for row in self.rows:
            if row['status'] == 'queued' and row['stage_epoch'] == epoch and self.membership.admitted(row['actor_id']):
                row.update(status='released', release_version=self.membership.version)
                self.ledger.append('delegation_released', copy.deepcopy(row), actor_id=row['actor_id'], stage_epoch=epoch, invocation_id=row['invocation_id'])
                released.append(copy.deepcopy(row))
        return released

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
                self.ledger.append('delegation_stage_transition',copy.deepcopy(row),actor_id=row['actor_id'],
                    stage_epoch=epoch,invocation_id=row['invocation_id'])
