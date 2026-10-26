"""Append-only evidence; event identity is distinct from identical content."""
from __future__ import annotations

import hashlib
import copy
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from .common import DynamicError, canonical, digest
from .schema import validate_contract


class EvidenceStore:
    def __init__(self, root: Path, branch_id: str):
        self.root, self.branch_id = root, branch_id
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, value: Any) -> str:
        data = canonical(value)
        identity = hashlib.sha256(data).hexdigest()
        target = self.root / (identity + ".json")
        if target.exists():
            if target.read_bytes() != data:
                raise DynamicError("hash_collision", identity)
        else:
            with target.open("xb") as stream:
                stream.write(data)
        return "evidence://" + identity

    def get(self, reference: str, *, branch_id: str) -> Any:
        if branch_id != self.branch_id:
            raise DynamicError("cross_branch_reference", "Evidence is branch scoped")
        if not reference.startswith("evidence://"):
            raise DynamicError("invalid_reference", reference)
        identity = reference.removeprefix("evidence://")
        if len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity):
            raise DynamicError("invalid_reference", reference)
        data = (self.root / (identity + ".json")).read_bytes()
        if hashlib.sha256(data).hexdigest() != identity:
            raise DynamicError("evidence_hash_mismatch", identity)
        return json.loads(data)


class DiskEventRows:
    """Legacy sequence view: iteration is streaming; never a retained payload list."""
    def __init__(self,ledger):self.ledger=ledger
    def __len__(self):return len(self.ledger.offsets)
    def __iter__(self):return self.ledger.iter_events()
    def __getitem__(self,index):
        if isinstance(index,slice):return [self.ledger._read_at(i) for i in range(*index.indices(len(self))) ]
        if index<0:index+=len(self)
        if not 0<=index<len(self):raise IndexError(index)
        return self.ledger._read_at(index)
    def __deepcopy__(self,memo):return list(self)
    def __add__(self,other):return list(self)+list(other)
    def __radd__(self,other):return list(other)+list(self)
    def __eq__(self,other):
        from itertools import zip_longest
        missing=object()
        return all(a==b for a,b in zip_longest(self,other,fillvalue=missing))


class EventLedger:
    """Disk authority, compact offsets and bounded serialized-byte LRU.

    The existing JSONL envelope and payload hash are unchanged. Append durability
    remains flush+fsync before returning or notifying coordination listeners.
    """
    CACHE_BYTES=2*1024*1024
    CACHE_ROWS=16
    def __init__(self,path:Path,branch_id:str,task_id:str):
        from array import array
        from collections import OrderedDict
        self.path,self.branch_id,self.task_id=path,branch_id,task_id
        self.lock=threading.RLock();self.listeners=[]
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.offsets=array('Q');self.by_type={};self.cache=OrderedDict();self.cached_bytes=0;self.peak_cached_bytes=0
        self.rows=DiskEventRows(self)
        if path.exists():
            with path.open('rb') as stream:
                while True:
                    offset=stream.tell();line=stream.readline()
                    if not line:break
                    try:row=json.loads(line)
                    except (ValueError,UnicodeError) as error:raise DynamicError('invalid_event_ledger','Invalid or incomplete tail at byte '+str(offset)) from error
                    number=len(self.offsets)+1
                    validate_contract('EventEnvelope',row)
                    if row['sequence']!=number or row['event_id']!=f'event_{number:08d}' or row['payload_hash']!=digest(row['payload']):raise DynamicError('invalid_event_ledger',f'Invalid event {number}')
                    if row['branch_id']!=branch_id or row['task_id']!=task_id:raise DynamicError('cross_branch_event','Ledger owner differs')
                    self.offsets.append(offset);self.by_type.setdefault(row['event_type'],array('Q')).append(number-1)

    def _cache(self,index,data):
        if len(data)>self.CACHE_BYTES:return
        previous=self.cache.pop(index,None)
        if previous is not None:self.cached_bytes-=len(previous)
        self.cache[index]=data;self.cached_bytes+=len(data)
        while self.cached_bytes>self.CACHE_BYTES or len(self.cache)>self.CACHE_ROWS:
            _,old=self.cache.popitem(last=False);self.cached_bytes-=len(old)
        self.peak_cached_bytes=max(self.peak_cached_bytes,self.cached_bytes)

    def _read_at(self,index):
        with self.lock:
            if index<0 or index>=len(self.offsets):raise IndexError(index)
            data=self.cache.get(index)
            if data is None:
                with self.path.open('rb') as stream:stream.seek(self.offsets[index]);data=stream.readline()
                self._cache(index,data)
            else:self.cache.move_to_end(index)
        return json.loads(data)

    def iter_events(self,*,event_type=None,actor_id=None,stage_epoch=None,request_id=None):
        with self.lock:
            count=len(self.offsets)
            # Compact index snapshot; no payload materialization.
            indices=tuple(self.by_type.get(event_type,())) if event_type is not None else range(count)
        for index in indices:
            row=self._read_at(index)
            if actor_id is not None and row['actor_id']!=actor_id:continue
            if stage_epoch is not None and row['stage_epoch']!=stage_epoch:continue
            if request_id is not None and row['request_id']!=request_id:continue
            yield row

    def content_hash(self):
        h=hashlib.sha256();h.update(b'[')
        for i,row in enumerate(self.iter_events()):
            if i:h.update(b',')
            h.update(canonical(row))
        h.update(b']');return h.hexdigest()

    def memory_stats(self):
        with self.lock:return {'event_count':len(self.offsets),'cached_rows':len(self.cache),'cached_bytes':self.cached_bytes,'peak_cached_bytes':self.peak_cached_bytes,'index_bytes':self.offsets.buffer_info()[1]*self.offsets.itemsize+sum(x.buffer_info()[1]*x.itemsize for x in self.by_type.values()),'authority':'complete fsynced JSONL'}

    def append(self,event_type:str,payload:dict,*,actor_id=None,stage_id='initial',stage_epoch=0,**references):
        from array import array
        allowed={'request_id','tool_call_id','message_id','invocation_id'}
        if references.keys()-allowed:raise DynamicError('invalid_event_reference',str(references.keys()-allowed))
        payload_bytes=canonical(payload)
        with self.lock:
            sequence=len(self.offsets)+1
            row={'schema_version':'1.0','event_id':f'event_{sequence:08d}','sequence':sequence,'monotonic_ns':time.monotonic_ns(),'branch_id':self.branch_id,'task_id':self.task_id,'stage_id':stage_id,'stage_epoch':stage_epoch,'actor_id':actor_id,'event_type':event_type,**{k:references.get(k) for k in sorted(allowed)},'payload_hash':hashlib.sha256(payload_bytes).hexdigest()}
            # Serialize the large payload once. JSON field order does not change parsed envelopes.
            raw=canonical(row)[:-1]+b',"payload":'+payload_bytes+b'}\n'
            value=json.loads(raw);validate_contract('EventEnvelope',value)
            with self.path.open('ab') as stream:
                offset=stream.tell();stream.write(raw);stream.flush();os.fsync(stream.fileno())
            self.offsets.append(offset);self.by_type.setdefault(event_type,array('Q')).append(sequence-1);self._cache(sequence-1,raw)
            listeners=tuple(self.listeners)
        # Never acquire coordination locks while holding the disk lock.
        for listener in listeners:listener(value)
        return value

    def require_event(self,identity):
        if not isinstance(identity,str) or not identity.startswith('event_') or not identity[6:].isdigit():raise DynamicError('missing_evidence_event',str(identity))
        index=int(identity[6:])-1
        try:row=self._read_at(index)
        except IndexError:raise DynamicError('missing_evidence_event',identity) from None
        if row['event_id']!=identity:raise DynamicError('missing_evidence_event',identity)
        return row
