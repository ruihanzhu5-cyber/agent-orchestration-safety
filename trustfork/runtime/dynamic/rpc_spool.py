"""Durable ordered RPC ingress; bounded backlog and no unbounded background queue."""
import os,threading,time
from pathlib import Path
from .common import DynamicError
class RpcSpool:
 def __init__(self,path,max_pending_bytes=64*1024*1024):
  self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
  self.stream=self.path.open('xb',buffering=0);self.condition=threading.Condition();self.max_pending=max_pending_bytes
  self.accepted=0;self.persisted=0;self.processed=0;self.high_water=0;self.frames=0;self.closed=False;self.failure=None;self.peak_frame=0
 def append(self,line):
  data=line.encode() if isinstance(line,str) else line
  with self.condition:
   while self.persisted-self.processed and self.persisted-self.processed+len(data)>self.max_pending and not self.closed:self.condition.wait(.1)
   if self.closed:raise DynamicError('rpc_spool_closed','Reader cannot append after close')
   self.accepted+=len(data);written=0
   while written<len(data):written+=self.stream.write(data[written:])
   os.fsync(self.stream.fileno());self.persisted+=len(data);self.frames+=1;self.peak_frame=max(self.peak_frame,len(data));self.high_water=max(self.high_water,self.persisted-self.processed)
   self.condition.notify_all()
 def finish(self,error=None):
  with self.condition:
   self.closed=True;self.failure=error;self.condition.notify_all()
 def frames_iter(self):
  offset=0
  with self.path.open('rb') as reader:
   while True:
    with self.condition:
     while offset>=self.persisted and not self.closed:self.condition.wait(.1)
     if offset>=self.persisted:
      if self.failure:raise self.failure
      return
    line=reader.readline()
    if not line.endswith(b'\n'):raise DynamicError('rpc_spool_incomplete_frame','Persisted RPC frame lacks newline')
    offset+=len(line);yield line,offset
 def acknowledge(self,end):
  with self.condition:
   if not self.processed<end<=self.persisted:raise DynamicError('rpc_spool_bad_ack','Processing must be strictly ordered')
   self.processed=end;self.condition.notify_all()
 def stats(self):
  with self.condition:return {'accepted_bytes':self.accepted,'persisted_bytes':self.persisted,'processed_bytes':self.processed,'unprocessed_tail_bytes':self.persisted-self.processed,'unpersisted_tail_bytes':self.accepted-self.persisted,'queue_high_water_bytes':self.high_water,'queue_limit_bytes':self.max_pending,'largest_frame_bytes':self.peak_frame,'frames':self.frames,'reader_closed':self.closed}
 def close(self):self.stream.close()
