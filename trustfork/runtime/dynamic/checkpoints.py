"""Complete idle-boundary checkpoints; restore must verify Docker state first."""
from __future__ import annotations
import copy
import time
from .common import DynamicError, digest, read_json, write_json
from .budget import Budget
from .membership import Membership
from .delegations import Delegations
from .mailbox import Mailbox
from .lifecycle import Lifecycle
from .scheduler import Scheduler
from .schema import validate_contract


def save_checkpoint(path, *, environment, client, sessions, membership, delegations, mailbox,
                    scheduler, budget, lifecycle, history, bindings):
    if scheduler.active or environment.active:
        raise DynamicError('checkpoint_active_work', 'Complete the current Pi/tool batch before checkpoint')
    states={a:client.call(identity,'export_session') for a,identity in sessions.items()}
    if any(x['delivery'][r]['status'] in ('claimed_for_input','input_frozen','submitted')
           for x in mailbox.messages for r in x['recipients']):
        raise DynamicError('checkpoint_active_input', 'Cannot snapshot an unresolved model exposure')
    env=environment.checkpoint_state(min(time.monotonic()+30,budget.deadline))
    env['workspace_export']=environment.export_state()
    snapshot={'schema_version':'1.0','protocol_version':'dynamic-join-v9-trajectory-portfolio',
        'task_id':environment.case['case_id'],'stage_id':lifecycle.stage_id,'stage_epoch':lifecycle.epoch,
        'lifecycle_state':lifecycle.state,'sessions':states,'directory':membership.directory(private=True),
        'candidates_visible':membership.candidates_visible,
        'delegations':copy.deepcopy(delegations.rows),'messages':copy.deepcopy(mailbox.messages),
        'scheduler':{'block_id':scheduler.block_id,'queue':list(scheduler.queue),'active':{},
            'ready_seq':scheduler.ready_seq,'batch_seq':scheduler.batch_seq,'startup':copy.deepcopy(scheduler.startup),
            'continuations':sorted(scheduler.continuations),**scheduler.coordination_snapshot()},
        'budget':budget.snapshot(),'history':copy.deepcopy(history),'bindings':copy.deepcopy(bindings),
        'environment':env,'prefix_events':copy.deepcopy(lifecycle.ledger.rows),
        'synthetic':getattr(client,'mode','scripted-test')!='api','validation':{'idle_boundary':True,'environment_restore':'not_yet_tested'}}
    snapshot['checkpoint_id']='checkpoint_'+digest(snapshot)
    snapshot['content_hash']=digest(snapshot)
    validate_contract('Checkpoint',snapshot)
    write_json(path,snapshot)
    return snapshot


def validate_checkpoint(snapshot):
    validate_contract('Checkpoint',snapshot)
    value=copy.deepcopy(snapshot);expected=value.pop('content_hash')
    if digest(value)!=expected:
        raise DynamicError('checkpoint_hash_mismatch','Checkpoint was changed')
    identifier=value.pop('checkpoint_id')
    if identifier!='checkpoint_'+digest(value):
        raise DynamicError('checkpoint_id_mismatch','Checkpoint identity is not its persisted content')
    if value['scheduler']['active'] or not value['validation']['idle_boundary']:
        raise DynamicError('checkpoint_active_work','Checkpoint has active request state')
    return snapshot


def restore_checkpoint(snapshot, *, environment, client, ledger, system_prompts, task_resources, independent_fork=False):
    validate_checkpoint(snapshot)
    verified=environment.restore(snapshot['environment'])
    membership=Membership(ledger)
    membership.members={r['actor_id']:copy.deepcopy(r) for r in snapshot['directory']['members']}
    membership.version=snapshot['directory']['version']
    membership.candidates_visible=snapshot['candidates_visible']
    delegations=Delegations(ledger,membership);delegations.rows=copy.deepcopy(snapshot['delegations'])
    mailbox=Mailbox(ledger,membership);mailbox.messages=copy.deepcopy(snapshot['messages'])
    # Message ownership is rebound privately; agent-facing IDs and text stay fixed.
    for row in mailbox.messages:row['branch_id']=ledger.branch_id
    lifecycle=Lifecycle(ledger,snapshot['stage_id'],snapshot['stage_epoch']);lifecycle.state=snapshot['lifecycle_state']
    scheduler=Scheduler(snapshot['scheduler']['block_id'],ledger,membership,lifecycle)
    from collections import deque
    scheduler.queue=deque(copy.deepcopy(snapshot['scheduler']['queue']))
    for key in ('ready_seq','batch_seq','startup'):setattr(scheduler,key,copy.deepcopy(snapshot['scheduler'][key]))
    scheduler.continuations=set(snapshot['scheduler'].get('continuations',[]))
    scheduler.restore_coordination(snapshot['scheduler'])
    delegations.startup_protected=scheduler.protects_delegation
    sessions={}
    for actor,state in snapshot['sessions'].items():
        identity,result=client.create_session(actor,branch_id=ledger.branch_id,task_id=ledger.task_id,
            system_prompt=system_prompts[actor],task_resources=task_resources,snapshot=state)
        sessions[actor]=identity
    return {'membership':membership,'delegations':delegations,'mailbox':mailbox,'lifecycle':lifecycle,
            'scheduler':scheduler,'budget':Budget.restore(snapshot['budget'],independent_fork=independent_fork),'sessions':sessions,
            'environment_verification':verified,'history':copy.deepcopy(snapshot['history'])}
