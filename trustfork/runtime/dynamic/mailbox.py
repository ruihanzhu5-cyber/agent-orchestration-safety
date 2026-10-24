"""Per-recipient FIFO and exposure proven from the actual successful payload."""
from __future__ import annotations
import copy
import threading
import uuid
from .common import DynamicError, digest


class Mailbox:
    def __init__(self, ledger, membership):
        self.ledger, self.membership, self.branch_id = ledger, membership, ledger.branch_id
        self.messages, self.lock = [], threading.RLock()

    def enqueue(self, sender, recipients, content, *, branch_id, epoch=0, message_id=None, parent_id=None):
        recipients = list(recipients)
        if branch_id != self.branch_id:
            raise DynamicError('cross_branch_message', 'Message branch does not match runtime')
        if not self.membership.admitted(sender) or not recipients or any(not self.membership.admitted(a) for a in recipients):
            raise DynamicError('message_member_unavailable', 'Sender or recipient is not admitted')
        if not isinstance(content, str) or len(set(recipients)) != len(recipients):
            raise DynamicError('invalid_message', 'Expected text and unique recipients')
        identity = message_id or uuid.uuid4().hex
        with self.lock:
            existing = next((m for m in self.messages if m['message_id'] == identity), None)
            if existing:
                if (existing['sender'], existing['recipients'], existing['content']) != (sender, recipients, content):
                    raise DynamicError('message_id_reused', identity)
                return copy.deepcopy(existing)
            row = {'message_id':identity, 'sender':sender, 'recipients':recipients, 'content':content,
                   'content_hash':digest(content), 'parent_id':parent_id, 'branch_id':branch_id, 'stage_epoch':epoch,
                   'delivery':{a:{'status':'queued', 'request_id':None, 'attempts':[]} for a in recipients}, 'terminal_status':None}
            event = self.ledger.append('message_enqueued', copy.deepcopy(row), actor_id=sender, stage_epoch=epoch, message_id=identity)
            row['created_event_id'] = event['event_id']
            self.messages.append(row)
            return copy.deepcopy(row)

    def claim(self, recipient, request_id, *, epoch, maintenance=False):
        if maintenance:
            return []
        if not self.membership.admitted(recipient):raise DynamicError('message_member_unavailable',recipient)
        with self.lock:
            rows = []
            for row in self.messages:
                state = row['delivery'].get(recipient)
                if row['stage_epoch'] == epoch and state and state['status'] == 'queued':
                    state.update(status='claimed_for_input', request_id=request_id)
                    self.ledger.append('message_delivery_transition',{'recipient':recipient,'status':'claimed_for_input'},
                        actor_id=recipient,stage_epoch=epoch,request_id=request_id,message_id=row['message_id'])
                    rows.append({'message_id':row['message_id'], 'sender':row['sender'], 'content':row['content'], 'content_hash':row['content_hash']})
            return copy.deepcopy(rows)

    def advance(self, recipient, request_id, status):
        previous = {'input_frozen':'claimed_for_input', 'submitted':'input_frozen'}
        if status not in previous:
            raise DynamicError('invalid_message_transition', status)
        with self.lock:
            for row in self.messages:
                state = row['delivery'].get(recipient)
                if state and state['request_id'] == request_id:
                    if state['status'] != previous[status]:
                        raise DynamicError('invalid_message_transition', state['status'] + ' -> ' + status)
                    state['status'] = status
                    self.ledger.append('message_delivery_transition',{'recipient':recipient,'status':status},
                        actor_id=recipient,stage_epoch=row['stage_epoch'],request_id=request_id,message_id=row['message_id'])

    def confirm(self, recipient, request_id, actual_input, *, successful, actual_request_id=None):
        actual = {x['message_id']: x for x in actual_input.get('peer_messages', [])}
        exposed = []
        with self.lock:
            for row in self.messages:
                state = row['delivery'].get(recipient)
                if state and state['request_id'] == request_id and state['status'] == 'submitted':
                    item = actual.get(row['message_id'])
                    if successful and item and item['content'] == row['content'] and item.get('content_hash') == row['content_hash']:
                        state.update(status='confirmed_exposure',confirmed_request_id=actual_request_id or request_id)
                        exposed.append(row['message_id'])
                        self.ledger.append('message_exposed', {'recipient':recipient, 'actual_input_hash':digest(actual_input)},
                            actor_id=recipient, stage_epoch=row['stage_epoch'], request_id=actual_request_id or request_id, message_id=row['message_id'])
                    else:
                        state['attempts'].append({'request_id':request_id, 'status':'generation_failed' if not successful else 'absent_from_actual_payload'})
                        state.update(status='queued', request_id=None)
                        self.ledger.append('message_delivery_transition',{'recipient':recipient,'status':'queued',
                            'reason':state['attempts'][-1]['status']},actor_id=recipient,
                            stage_epoch=row['stage_epoch'],request_id=request_id,message_id=row['message_id'])
        return exposed

    def stage_transition(self, old_epoch, new_epoch, *, new_session):
        with self.lock:
            for row in self.messages:
                if row['stage_epoch'] != old_epoch:
                    continue
                pending = [s for s in row['delivery'].values() if s['status'] != 'confirmed_exposure']
                if new_session:
                    for state in pending:
                        state.update(status='cancelled_new_session', request_id=None)
                    if pending:
                        row['terminal_status'] = 'cancelled_new_session'
                elif pending:
                    if any(s['status'] != 'queued' for s in pending):
                        raise DynamicError('active_message_at_stage_boundary', row['message_id'])
                    row['stage_epoch'], row['carried_from_epoch'] = new_epoch, old_epoch
                if pending:self.ledger.append('message_stage_transition',{'new_epoch':new_epoch,'new_session':new_session,
                    'delivery':row['delivery'],'carried_from_epoch':row.get('carried_from_epoch')},stage_epoch=old_epoch,message_id=row['message_id'])
