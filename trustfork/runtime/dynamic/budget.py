"""Host-owned attempt accounting; refused behavior is never retried."""
from __future__ import annotations
import copy
import threading
import time
from .common import DynamicError


class Budget:
    def __init__(self, request_limit=None, token_limit=None, per_request=None, stage_seconds=None):
        from .experiment_config import resolve_runtime_budget
        defaults=resolve_runtime_budget('gpt4o')
        request_limit=defaults['request_limit'] if request_limit is None else request_limit
        token_limit=defaults['token_limit'] if token_limit is None else token_limit
        per_request=defaults['per_request'] if per_request is None else per_request
        stage_seconds=defaults['stage_seconds'] if stage_seconds is None else stage_seconds
        if any(type(x) is not int or x<=0 for x in (request_limit,token_limit,per_request,stage_seconds)):
            raise DynamicError('invalid_runtime_budget','Positive integer resource limits required')
        self.request_limit, self.token_limit, self.per_request = request_limit, token_limit, per_request
        self.stage_seconds = stage_seconds
        self.deadline = time.monotonic() + stage_seconds
        self.attempts, self.output_tokens, self.lock = [], 0, threading.RLock()

    def available(self):
        return len(self.attempts) < self.request_limit and self.remaining_tokens() >= self.per_request and time.monotonic() < self.deadline

    def remaining_tokens(self):
        reserved = sum(x['max_output_tokens'] for x in self.attempts if x['status'] == 'reserved')
        return self.token_limit - self.output_tokens - reserved

    def termination_reason(self):
        if time.monotonic()>=self.deadline:return 'time_limit'
        if len(self.attempts)>=self.request_limit:return 'request_limit'
        if self.token_limit-self.output_tokens<self.per_request:return 'token_limit'
        return None

    def exhausted(self):
        return len(self.attempts)>=self.request_limit or self.token_limit-self.output_tokens<self.per_request or time.monotonic()>=self.deadline

    def reserve(self, request_id, attempt, *, maintenance=False, actor_id=None):
        with self.lock:
            if not self.available():
                raise DynamicError('budget_waiting_for_inflight' if not self.exhausted() else 'budget_exhausted',
                                   'Waiting for temporary reservations' if not self.exhausted() else 'Full generation no longer fits task budget')
            if not 0 <= attempt <= 2:
                raise DynamicError('transport_retry_limit', request_id)
            identity = f'{request_id}.attempt{attempt}'
            if any(x['attempt_id'] == identity for x in self.attempts):
                raise DynamicError('duplicate_attempt', identity)
            record = {'request_id': request_id, 'attempt_id': identity, 'actor_id': actor_id,
                      'maintenance': maintenance, 'status': 'reserved', 'output_tokens': None,
                      'max_output_tokens': self.per_request}
            self.attempts.append(record)
            return copy.deepcopy(record)

    def finish(self, attempt_id, *, output_tokens, status, cost=None):
        with self.lock:
            record = next((x for x in self.attempts if x['attempt_id'] == attempt_id), None)
            if record is None or record['status'] != 'reserved':
                raise DynamicError('attempt_not_reserved', attempt_id)
            if not isinstance(output_tokens, int) or output_tokens < 0:
                raise DynamicError('invalid_token_usage', attempt_id)
            if output_tokens > record['max_output_tokens']:
                raise DynamicError('provider_output_limit_breached', attempt_id)
            record.update(output_tokens=output_tokens, status=status, cost=cost)
            self.output_tokens += output_tokens

    def snapshot(self):
        return {'request_limit': self.request_limit, 'token_limit': self.token_limit, 'per_request': self.per_request,
                'deadline_wall': time.time()+max(0,self.deadline-time.monotonic()),
                'stage_seconds': self.stage_seconds, 'remaining_seconds': max(0, self.deadline - time.monotonic()),
                'attempts': copy.deepcopy(self.attempts), 'output_tokens': self.output_tokens}

    @classmethod
    def restore(cls, snapshot, *, independent_fork=False):
        obj = cls(**{k: snapshot[k] for k in ('request_limit', 'token_limit', 'per_request', 'stage_seconds')})
        remaining=snapshot['remaining_seconds'] if independent_fork else max(0,min(snapshot['remaining_seconds'],snapshot.get('deadline_wall',time.time()+snapshot['remaining_seconds'])-time.time()))
        obj.deadline = time.monotonic() + remaining
        obj.attempts, obj.output_tokens = copy.deepcopy(snapshot['attempts']), snapshot['output_tokens']
        return obj

    def new_stage(self):
        self.deadline = time.monotonic() + self.stage_seconds
