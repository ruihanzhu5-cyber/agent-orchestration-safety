"""ready_fifo_v1: the only ready queue lives in the Python host."""
from __future__ import annotations
import hashlib
import threading
import time
import copy
from collections import deque
from .common import DynamicError


class Scheduler:
    def __init__(self, block_id, ledger, membership, lifecycle):
        self.block_id, self.ledger, self.membership, self.lifecycle = block_id, ledger, membership, lifecycle
        self.queue, self.active, self.ready_seq, self.batch_seq = deque(), {}, 0, 0
        self.startup = {a:{'requests':0, 'status':'not_admitted'} for a in ('C', 'D')}
        self.idle_versions, self.lock = set(), threading.RLock()
        self.continuations=set();self.work_available=None
        self.waiting={};self.versions={a:0 for a in ("Main","A","B","C","D")};self.wake_results={}
        self.changed=threading.Condition(self.lock)

    def enqueue_batch(self, actors, *, reason, maintenance=False):
        with self.lock:
            self.batch_seq += 1
            epoch = self.lifecycle.epoch
            key = lambda a: hashlib.sha256(f'{self.block_id}|{epoch}|{self.batch_seq}|{a}'.encode()).hexdigest()
            for actor in sorted(set(actors), key=key):
                if not self.membership.admitted(actor):
                    raise DynamicError('unadmitted_ready_actor', actor)
                if actor in self.active or any(x['actor_id'] == actor for x in self.queue):
                    continue
                self.ready_seq += 1
                self.queue.append({'actor_id':actor, 'ready_seq':self.ready_seq, 'batch_seq':self.batch_seq,
                                   'stage_epoch':epoch, 'reason':reason, 'maintenance':maintenance})

    def permit(self, *, actors=None):
        with self.lock:
            for row in list(self.queue):
                actor = row['actor_id']
                if actors is not None and actor not in actors:continue
                if row['stage_epoch'] != self.lifecycle.epoch:
                    raise DynamicError('old_epoch_ready_item', actor)
                if actor in self.active:
                    continue
                if actor != 'Main' and (not self.lifecycle.worker_permitted() or sum(a != 'Main' for a in self.active) >= 4):
                    continue
                if not self.membership.admitted(actor):
                    self.queue.remove(row)
                    continue
                if actor!='Main' and self.work_available is not None and not self.work_available(actor):
                    self.queue.remove(row)
                    self.ledger.append('stale_ready_marker_discarded',row,actor_id=actor,
                        stage_id=self.lifecycle.stage_id,stage_epoch=self.lifecycle.epoch)
                    continue
                self.queue.remove(row)
                self.active[actor] = row
                if actor in self.startup and not row['maintenance'] and self.startup[actor]['status'] == 'open':
                    self.startup[actor]['requests'] += 1
                self.ledger.append('permit_granted', row, actor_id=actor, stage_epoch=self.lifecycle.epoch)
                return row.copy()
        return None

    def begin_startup(self, actors):
        for actor in actors:
            if not self.membership.admitted(actor):
                raise DynamicError('startup_unadmitted', actor)
            self.startup[actor] = {'requests':0, 'status':'open',
                'stage_epoch':self.lifecycle.epoch,'stage_id':self.lifecycle.stage_id,
                'invocation_id':None}

    def protects_delegation(self, row):
        """Protection belongs to the current initial slice, never its label alone."""
        value=self.startup.get(row['actor_id'],{})
        return bool(row.get('source')=='runtime_startup' and value.get('status')=='open'
            and row['stage_epoch']==self.lifecycle.epoch==value.get('stage_epoch')
            and row.get('stage_id')==self.lifecycle.stage_id==value.get('stage_id')
            and value.get('invocation_id')==row.get('invocation_id'))

    def bind_startup(self, row):
        value=self.startup[row['actor_id']]
        if value['status']!='open' or row['stage_epoch']!=value['stage_epoch']:
            raise DynamicError('invalid_startup_binding',row['invocation_id'])
        value['invocation_id']=row['invocation_id']

    def _close_startup(self,actor,reason):
        value=self.startup[actor];value['status']=reason
        had_message=any(e['event_type']=='message_enqueued' and e['actor_id']==actor and
            e['stage_epoch']==self.lifecycle.epoch for e in self.ledger.iter_events())
        actual=sum(e['event_type']=='model_request_submitted' and e['actor_id']==actor and
            e['stage_epoch']==self.lifecycle.epoch for e in self.ledger.iter_events())
        self.ledger.append('startup_slice_closed',{'requests':value['requests'],'actual_requests':actual,
            'terminal_status':reason,'message_status':'message_queued' if had_message else 'no_message_at_slice_end'},
            actor_id=actor,stage_id=self.lifecycle.stage_id,stage_epoch=self.lifecycle.epoch)

    def complete(self, actor, *, unfinished=False, terminal_status=None, outcome=None):
        with self.lock:
            if actor not in self.active:
                raise DynamicError('actor_not_active', actor)
            row = self.active.pop(actor)
            if row['stage_epoch'] != self.lifecycle.epoch:
                raise DynamicError('late_old_epoch_completion', actor)
            if outcome is not None:
                unfinished=outcome['state'] in ('continue','waiting')
                if outcome['state']=='resource_ended':terminal_status='resource_ended'
            startup = self.startup.get(actor)
            if startup and startup['status'] == 'open' and not row['maintenance']:
                if terminal_status or not unfinished:
                    startup['status'] = terminal_status or 'completed'
                elif startup['requests'] >= 4:
                    startup['status'] = 'four_request_limit'
                if startup['status']!='open':
                    self._close_startup(actor,startup['status'])
            if outcome is not None:
                state=outcome['state']
                if state=='waiting' and not terminal_status:
                    self.continuations.add(actor)
                    intent=self.wait_intent(actor,after_version=outcome['after_version'],timeout_seconds=outcome['timeout_seconds'],pending_work=outcome['pending_work'])
                    if intent['status']=='wait_requested':
                        self.waiting[actor]={'after_version':intent['version'],'deadline_wall':time.time()+intent['timeout_seconds'],'stage_epoch':self.lifecycle.epoch}
                        self.ledger.append('actor_wait_registered',{'version':intent['version'],'deadline_wall':self.waiting[actor]['deadline_wall']},actor_id=actor,stage_epoch=self.lifecycle.epoch)
                        return 'waiting'
                    self.wake_results[actor]={'reason':intent['status'],'version':self.versions[actor]}
                    self.enqueue_batch([actor],reason=intent['status'])
                    return intent['status']
                unfinished=state=='continue'
                terminal_status='resource_ended' if state=='resource_ended' else terminal_status
            if unfinished and not terminal_status:
                self.continuations.add(actor)
                self.enqueue_batch([actor], reason='unfinished_work')
            else:self.continuations.discard(actor)

    def observable_version(self,actor):
        with self.lock:return self.versions[actor]

    def wait_intent(self,actor,*,after_version,timeout_seconds,pending_work):
        with self.lock:
            if type(after_version) is not int or after_version<0 or after_version>self.versions[actor] or type(timeout_seconds) not in (int,float) or not 0<timeout_seconds<=300:
                raise DynamicError('invalid_wait_parameters','after_version must be an observed integer; timeout_seconds in (0,300]')
            status='changed' if after_version<self.versions[actor] else 'no_pending_work' if not pending_work else 'wait_requested'
            return {'status':status,'version':self.versions[actor],'timeout_seconds':timeout_seconds}

    def notify(self,actors,reason):
        with self.lock:
            for actor in set(actors):
                self.versions[actor]+=1
                if actor in self.waiting:
                    self.waiting.pop(actor)
                    self.wake_results[actor]={'reason':reason,'version':self.versions[actor]}
                    if self.membership.admitted(actor):self.enqueue_batch([actor],reason='wait_'+reason)
            self.changed.notify_all()

    def observe_event(self,row):
        kind=row['event_type'];p=row['payload']
        if kind=='message_enqueued':self.notify(p['recipients'],'message')
        elif kind.startswith('delegation_'):
            self.notify(['Main',p['actor_id']],'delegation_'+p['status'])
        elif kind in ('members_admitted','member_released','candidates_published'):
            if kind=='member_released':self.cancel_waits('member_released',actors=[p['actor_id']],requeue=False)
            self.notify(list(self.versions),'membership')

    def poll_waiters(self,*,now=None):
        with self.lock:
            now=time.time() if now is None else now
            for actor,row in list(self.waiting.items()):
                if now>=row['deadline_wall']:self.cancel_waits('timeout',actors=[actor])

    def cancel_waits(self,reason,*,actors=None,requeue=True):
        with self.lock:
            for actor in list(self.waiting):
                if actors is not None and actor not in actors:continue
                self.waiting.pop(actor);self.wake_results[actor]={'reason':reason,'version':self.versions[actor]}
                self.ledger.append('actor_wait_ended',self.wake_results[actor],actor_id=actor,stage_epoch=self.lifecycle.epoch)
                if requeue and self.membership.admitted(actor):self.enqueue_batch([actor],reason='wait_'+reason)
            self.changed.notify_all()

    def coordination_snapshot(self):
        with self.lock:return copy.deepcopy({'waiting':self.waiting,'versions':self.versions,'wake_results':self.wake_results})

    def restore_coordination(self,value):
        with self.lock:
            for key in ('waiting','versions','wake_results'):
                if key in value:setattr(self,key,copy.deepcopy(value[key]))
            self.poll_waiters()

    def terminate_startup(self, reason):
        for actor,value in self.startup.items():
            if value['status'] == 'open':
                self._close_startup(actor,reason)

    def final_allowed(self, *, hard_limit=False):
        return hard_limit or all(x['status'] != 'open' for x in self.startup.values())

    def neutral_wake(self, state_version):
        if self.active or self.queue or self.waiting or state_version in self.idle_versions:
            return False
        self.idle_versions.add(state_version)
        self.enqueue_batch(['Main'], reason='neutral_idle_wake')
        return True

    def reset_epoch(self, epoch):
        if self.active:
            raise DynamicError('active_epoch_reset', 'Drain or cancel active turns first')
        self.cancel_waits("stage_deadline",requeue=False)
        self.queue = deque(x for x in self.queue if x['stage_epoch'] != epoch)
        self.continuations.clear()

    def consume_ready_marker(self, actor):
        if actor in self.active:
            raise DynamicError('actor_already_active',actor)
        self.queue=deque(x for x in self.queue if x['actor_id']!=actor)
