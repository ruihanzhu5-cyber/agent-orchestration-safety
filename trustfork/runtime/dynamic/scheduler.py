"""ready_fifo_v1: the only ready queue lives in the Python host."""
from __future__ import annotations
import hashlib
import threading
from collections import deque
from .common import DynamicError


class Scheduler:
    def __init__(self, block_id, ledger, membership, lifecycle):
        self.block_id, self.ledger, self.membership, self.lifecycle = block_id, ledger, membership, lifecycle
        self.queue, self.active, self.ready_seq, self.batch_seq = deque(), {}, 0, 0
        self.startup = {a:{'requests':0, 'status':'not_admitted'} for a in ('C', 'D')}
        self.idle_versions, self.lock = set(), threading.RLock()

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
            self.startup[actor] = {'requests':0, 'status':'open'}

    def complete(self, actor, *, unfinished=False, terminal_status=None):
        with self.lock:
            if actor not in self.active:
                raise DynamicError('actor_not_active', actor)
            row = self.active.pop(actor)
            if row['stage_epoch'] != self.lifecycle.epoch:
                raise DynamicError('late_old_epoch_completion', actor)
            startup = self.startup.get(actor)
            if startup and startup['status'] == 'open' and not row['maintenance']:
                if terminal_status or not unfinished:
                    startup['status'] = terminal_status or 'completed'
                elif startup['requests'] >= 4:
                    startup['status'] = 'four_request_limit'
            if unfinished and not terminal_status:
                self.enqueue_batch([actor], reason='unfinished_work')

    def terminate_startup(self, reason):
        for value in self.startup.values():
            if value['status'] == 'open':
                value['status'] = reason

    def final_allowed(self, *, hard_limit=False):
        return hard_limit or all(x['status'] != 'open' for x in self.startup.values())

    def neutral_wake(self, state_version):
        if self.active or self.queue or state_version in self.idle_versions:
            return False
        self.idle_versions.add(state_version)
        self.enqueue_batch(['Main'], reason='neutral_idle_wake')
        return True

    def reset_epoch(self, epoch):
        if self.active:
            raise DynamicError('active_epoch_reset', 'Drain or cancel active turns first')
        self.queue = deque(x for x in self.queue if x['stage_epoch'] != epoch)

    def consume_ready_marker(self, actor):
        if actor in self.active:
            raise DynamicError('actor_already_active',actor)
        self.queue=deque(x for x in self.queue if x['actor_id']!=actor)
