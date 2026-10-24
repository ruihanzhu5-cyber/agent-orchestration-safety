"""Host-owned attempt accounting; refused behavior is never retried."""
from __future__ import annotations
import copy
import threading
import time
from .common import DynamicError


class Budget:
    def __init__(self, request_limit=120, token_limit=48000, per_request=4096, stage_seconds=1200):
        self.request_limit, self.token_limit, self.per_request = request_limit, token_limit, per_request
        self.stage_seconds = stage_seconds
        self.deadline = time.monotonic() + stage_seconds
        self.attempts, self.output_tokens, self.lock = [], 0, threading.RLock()

    def available(self):
        return len(self.attempts) < self.request_limit and self.remaining_tokens() > 0 and time.monotonic() < self.deadline

    def remaining_tokens(self):
        reserved = sum(x['max_output_tokens'] for x in self.attempts if x['status'] == 'reserved')
        return self.token_limit - self.output_tokens - reserved

    def exhausted(self):
        return len(self.attempts)>=self.request_limit or self.output_tokens>=self.token_limit or time.monotonic()>=self.deadline

    def reserve(self, request_id, attempt, *, maintenance=False, actor_id=None):
        with self.lock:
            if not self.available():
                raise DynamicError('budget_exhausted', 'Team request, output token or stage limit')
            if not 0 <= attempt <= 2:
                raise DynamicError('transport_retry_limit', request_id)
            identity = f'{request_id}.attempt{attempt}'
            if any(x['attempt_id'] == identity for x in self.attempts):
                raise DynamicError('duplicate_attempt', identity)
            record = {'request_id': request_id, 'attempt_id': identity, 'actor_id': actor_id,
                      'maintenance': maintenance, 'status': 'reserved', 'output_tokens': None,
                      'max_output_tokens': min(self.per_request, self.remaining_tokens())}
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
                'stage_seconds': self.stage_seconds, 'remaining_seconds': max(0, self.deadline - time.monotonic()),
                'attempts': copy.deepcopy(self.attempts), 'output_tokens': self.output_tokens}

    @classmethod
    def restore(cls, snapshot):
        obj = cls(**{k: snapshot[k] for k in ('request_limit', 'token_limit', 'per_request', 'stage_seconds')})
        obj.deadline = time.monotonic() + snapshot['remaining_seconds']
        obj.attempts, obj.output_tokens = copy.deepcopy(snapshot['attempts']), snapshot['output_tokens']
        return obj

    def new_stage(self):
        self.deadline = time.monotonic() + self.stage_seconds
