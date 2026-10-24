"""Actor-visible cross-task state; no environment files or private peer sessions."""
import copy
from .common import DynamicError, digest


class History:
    def __init__(self):
        self.tasks=[]
        self.actor_states={a:[] for a in ('Main','A','B')}
        self.synthetic=False

    def add_task(self, task_id, sessions, *, synthetic, status):
        if task_id in self.tasks or set(sessions)!=set(self.actor_states):
            raise DynamicError('invalid_history_task', 'Require a distinct task and exactly Main/A/B states')
        if len(self.tasks)>=2:
            raise DynamicError('history_already_complete', task_id)
        self.tasks.append(task_id)
        self.synthetic |= synthetic
        for actor,snapshot in sessions.items():
            if snapshot['config']['actor_id']!=actor or snapshot['config']['task_id']!=task_id:
                raise DynamicError('history_actor_scope_mismatch', actor)
            self.actor_states[actor].append({'task_id':task_id,'status':status,'session':copy.deepcopy(snapshot),
                                           'synthetic':synthetic,'snapshot_hash':digest(snapshot)})

    def for_actor(self, actor, *, target_task):
        if actor not in self.actor_states or target_task in self.tasks:
            raise DynamicError('invalid_history_carry', str((actor,target_task)))
        return copy.deepcopy(self.actor_states[actor])

    def export(self):
        return {'tasks':self.tasks.copy(),'actor_states':copy.deepcopy(self.actor_states),'synthetic':self.synthetic,
                'environment_carry':False,'actual_real_model_calls':0 if self.synthetic else None}
