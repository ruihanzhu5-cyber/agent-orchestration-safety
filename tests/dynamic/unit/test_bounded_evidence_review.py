import json,hashlib,tracemalloc
from pathlib import Path
from trustfork.runtime.dynamic.common import canonical,digest,write_json
from trustfork.runtime.dynamic.events import EventLedger

def test_disk_ledger_restore_iter_query_and_bounded_cache(tmp_path,monkeypatch):
 p=tmp_path/'events.jsonl';l=EventLedger(p,'b','p001');expected=[]
 for i in range(120):
  row=l.append('pi_event',{'text':'完整🙂'*2048,'turn':i},actor_id='A',request_id=str(i))
  expected.append(digest(row));row['payload']['text']='caller mutation'
 assert not isinstance(l.rows,list)
 assert l.memory_stats()['cached_bytes']<=2*1024*1024
 original=Path.read_text
 def no_whole_read(path,*a,**k):
  if path==p:raise AssertionError('whole ledger read forbidden')
  return original(path,*a,**k)
 monkeypatch.setattr(Path,'read_text',no_whole_read)
 restored=EventLedger(p,'b','p001')
 assert [digest(e) for e in restored.iter_events()]==expected
 assert restored.content_hash()==digest(list(restored.iter_events()))
 assert [e['request_id'] for e in restored.iter_events(event_type='pi_event',actor_id='A')]==[str(i) for i in range(120)]
 assert digest(restored.require_event('event_00000001'))==expected[0]
 assert restored.memory_stats()['cached_bytes']<=2*1024*1024


def test_export_large_compressible_jsonl_is_bounded_and_atomic(tmp_path):
 from trustfork.runtime.dynamic.review_export import export_campaign
 source=tmp_path/'source';source.mkdir();write_json(source/'campaign.json',{'status':'stopped','campaign_id':'bounded-offline','identity':{'commit':'synthetic'}})
 path=source/'tests/large.jsonl';path.parent.mkdir()
 with path.open('wb') as f:
  for i in range(160):f.write(canonical({'sequence':i,'payload':'abc🙂'*32768})+b'\n')
 before=hashlib.sha256(path.read_bytes()).hexdigest()
 tracemalloc.start()
 result=export_campaign(source,tmp_path/'public',max_part_bytes=512*1024,max_total_bytes=2*1024*1024)
 _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
 # Input >35MiB; threshold allows 20 shard buffers plus interpreter/redactor overhead,
 # deliberately far below cumulative uncompressed output. No absolute RSS assertion.
 assert peak<20*512*1024+8*1024*1024,peak
 assert hashlib.sha256(path.read_bytes()).hexdigest()==before
 assert (tmp_path/'public/manifest.json').exists()
 write_json(tmp_path/'export-resource-measurement.json',{'input_bytes':path.stat().st_size,'python_tracemalloc_peak_bytes':peak,'shard_bytes':512*1024,'peak_limit_bytes':20*512*1024+8*1024*1024,'streaming_memory':result['streaming_memory'],'synthetic':True,'real_calls':0})
 assert result['streaming_memory']['uncompressed_shards_retained']==0
 from trustfork.runtime.dynamic.review_packing import read_review_bytes
 out=[]
 for p in sorted((tmp_path/'public/evidence/tests').glob('large.part-*')):out.extend(json.loads(x) for x in read_review_bytes(tmp_path/'public',str(p.relative_to(tmp_path/'public'))).splitlines())
 assert [x['sequence'] for x in out]==list(range(160)) and all(x['payload']=='abc🙂'*32768 for x in out)


def test_slow_rpc_consumer_preserves_scope_order_cancel_and_tail(tmp_path):
 import threading,time
 from trustfork.runtime.dynamic.rpc_spool import RpcSpool
 spool=RpcSpool(tmp_path/'frames',max_pending_bytes=2048);seen=[]
 frames=[{'kind':'event','request_id':str(i//3),'part':i,'text':'🙂'*128} for i in range(120)]+[{'kind':'cancelled','request_id':'last'},{'kind':'result','request_id':'last'}]
 def consume():
  for line,end in spool.frames_iter():
   time.sleep(.001);seen.append(json.loads(line));spool.acknowledge(end)
 worker=threading.Thread(target=consume);worker.start()
 for frame in frames:spool.append(canonical(frame)+b'\n')
 spool.finish();worker.join(10)
 assert not worker.is_alive() and seen==frames
 stats=spool.stats();assert stats['unprocessed_tail_bytes']==0 and stats['accepted_bytes']==stats['persisted_bytes']==stats['processed_bytes']
 assert stats['queue_high_water_bytes']<=max(stats['queue_limit_bytes'],stats['largest_frame_bytes'])
 spool.close()


def test_incomplete_rpc_frame_retains_unprocessed_tail(tmp_path):
 import pytest
 from trustfork.runtime.dynamic.rpc_spool import RpcSpool
 from trustfork.runtime.dynamic.common import DynamicError
 spool=RpcSpool(tmp_path/'frames');spool.append(b'{"kind":"partial"');spool.finish()
 with pytest.raises(DynamicError,match='rpc_spool_incomplete_frame'):list(spool.frames_iter())
 assert spool.stats()['unprocessed_tail_bytes']>0
 spool.close()


def test_failed_fsync_reports_received_but_not_durable_rpc_bytes(tmp_path,monkeypatch):
 import os,pytest
 from trustfork.runtime.dynamic.rpc_spool import RpcSpool
 spool=RpcSpool(tmp_path/'frames')
 def failed(fd):raise OSError('injected durable-write failure')
 monkeypatch.setattr(os,'fsync',failed)
 with pytest.raises(OSError,match='durable-write failure'):spool.append(b'{"kind":"event"}\n')
 stats=spool.stats()
 assert stats['accepted_bytes']>0 and stats['persisted_bytes']==0
 assert stats['unpersisted_tail_bytes']==stats['accepted_bytes']
 spool.finish(OSError('injected failure'))
 with pytest.raises(OSError):list(spool.frames_iter())
 spool.close()
