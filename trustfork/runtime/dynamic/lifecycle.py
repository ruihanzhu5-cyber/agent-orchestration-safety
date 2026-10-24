"""Explicit stage and finalization boundaries; no permission after closing."""
from __future__ import annotations

import time
from .common import DynamicError


TRANSITIONS = {
    'PLANNING': {'PLAN_READY', 'FINAL_PROPOSED'}, 'PLAN_READY': {'JOINING', 'COORDINATING', 'RUNNING'},
    'JOINING': {'COORDINATING'}, 'COORDINATING': {'RUNNING', 'FINAL_PROPOSED'},
    'RUNNING': {'STAGE_CLOSING', 'FINAL_PROPOSED'}, 'STAGE_CLOSING': {'RUNNING', 'FINAL_PROPOSED'},
    'FINAL_PROPOSED': {'CLOSING', 'RUNNING'}, 'CLOSING': {'RUNNING', 'FROZEN'}, 'FROZEN': {'SCORING'}, 'SCORING': set(),
}


class Lifecycle:
    def __init__(self, ledger, stage_id='initial', stage_epoch=0):
        self.ledger, self.stage_id, self.epoch = ledger, stage_id, stage_epoch
        self.state = 'PLANNING'
        self.final_revision = None

    def transition(self, target, **payload):
        if target not in TRANSITIONS[self.state]:
            raise DynamicError('invalid_lifecycle_transition', self.state + ' -> ' + target)
        previous, self.state = self.state, target
        self.ledger.append('lifecycle', {'from': previous, 'to': target, **payload}, stage_id=self.stage_id, stage_epoch=self.epoch)

    def worker_permitted(self):
        return self.state == 'RUNNING'

    def propose_final(self, revision):
        self.transition('FINAL_PROPOSED', input_revision=revision)
        self.final_revision = revision

    def finalize(self, environment, *, stage_deadline, current_revision, has_budget):
        self.transition('CLOSING')
        outcome = environment.quiesce(min(time.monotonic() + 30, stage_deadline))
        if current_revision() != self.final_revision and has_budget() and time.monotonic() < stage_deadline:
            environment.accepting = True
            self.transition('RUNNING', reason='final_stale', closing=outcome)
            return {'status': 'final_stale'}
        try:
            frozen = environment.freeze()
            exported = environment.export_state()
        except DynamicError as error:
            self.ledger.append('freeze_failed', error.record(), stage_id=self.stage_id, stage_epoch=self.epoch)
            raise
        self.transition('FROZEN', freeze=frozen, closing=outcome)
        return exported

    def close_stage(self, environment, *, next_stage, deadline, drain, reset, migrate):
        self.transition('STAGE_CLOSING')
        closing_epoch = self.epoch
        environment.quiesce(min(time.monotonic() + 30, deadline))
        drain(closing_epoch)
        if environment.active:
            raise DynamicError('old_epoch_active', 'Cannot advance while old work is active')
        if next_stage['new_session']:
            reset(closing_epoch)
        else:
            migrate(closing_epoch, closing_epoch + 1)
        self.epoch += 1
        self.stage_id = next_stage['id']
        environment.accepting = True
        self.transition('RUNNING', new_session=next_stage['new_session'])
