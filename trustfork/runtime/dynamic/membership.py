"""Versioned directory and atomic admission, without a separate manager."""
import copy
import threading
from .common import DynamicError


class Membership:
    def __init__(self, ledger):
        self.ledger, self.version = ledger, 0
        self.lock=threading.RLock()
        self.candidates_visible = False
        self.members = {a: {'actor_id': a, 'status': 'admitted' if a in ('Main', 'A', 'B') else 'candidate',
                            'joined_event_id': None} for a in ('Main', 'A', 'B', 'C', 'D')}

    def admitted(self, actor):
        with self.lock:return actor in self.members and self.members[actor]['status'] == 'admitted'

    def status(self,actor):
        with self.lock:return self.members[actor]['status']

    def admit_atomic(self, actors, *, stage_id='initial', stage_epoch=0, request_id=None):
        with self.lock:return self._admit_atomic(actors,stage_id=stage_id,stage_epoch=stage_epoch,request_id=request_id)

    def _admit_atomic(self, actors, *, stage_id, stage_epoch,request_id):
        actors = list(actors)
        if not actors or len(set(actors)) != len(actors) or any(a not in ('C', 'D') or self.members[a]['status'] != 'candidate' for a in actors):
            raise DynamicError('invalid_admission', str(actors))
        self.version += 1
        event = self.ledger.append('members_admitted', {'actor_ids': actors, 'directory_version':self.version}, stage_id=stage_id, stage_epoch=stage_epoch,request_id=request_id)
        for a in actors:
            self.members[a].update(status='admitted', joined_event_id=event['event_id'])
        return {'directory_version':self.version, 'members': self.directory()}

    def release(self, actor, *, stage_id='initial',stage_epoch=0,request_id=None):
        with self.lock:return self._release(actor,stage_id=stage_id,stage_epoch=stage_epoch,request_id=request_id)

    def _release(self,actor,**scope):
        if actor in ('Main',) or not self.admitted(actor):
            raise DynamicError('invalid_member_release', actor)
        self.version += 1
        self.members[actor]['status'] = 'released'
        return self.ledger.append('member_released', {'actor_id':actor, 'directory_version':self.version},actor_id='Main',**scope)

    def directory(self, *, private=False):
        with self.lock:
            rows=[r for r in self.members.values() if private or self.candidates_visible or r['status']!='candidate']
            return {'version': self.version, 'members': copy.deepcopy(rows)}

    def publish_candidates(self):
        self.candidates_visible=True
        self.version+=1
        self.ledger.append('candidates_published',{'directory_version':self.version})
