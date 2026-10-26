import json,gzip
from trustfork.runtime.dynamic.review_packing import pack_review_files,read_review_bytes,sha
from trustfork.runtime.dynamic.common import canonical
def test_packing_preserves_duplicate_large_records_references_and_conversation(tmp_path):
 payload={'text':'synthetic-risk '*30000,'id':'event-kept'}
 raw=canonical(payload)+b'\n'
 files={'README.md':b'[A](evidence/a.json)\n','evidence/a.json':raw,'evidence/version/a.json':raw,
 'events.part-0000.jsonl':canonical({'large_record_ref':'evidence/a.json','export_hash':sha(raw),'original_sequence':7})+b'\n',
 'trajectories/run/conversation.md':('# Run\n\n## actor=A request=R event=E\n\n~~~json\n'+json.dumps(payload)+'\n~~~\n').encode()}
 out,rename,note=pack_review_files(files)
 assert len(out['evidence/a.json.gz'])<len(raw)/20
 for name,data in out.items():
  p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
 assert read_review_bytes(tmp_path,'evidence/a.json.gz')==raw
 assert read_review_bytes(tmp_path,'evidence/version/a.json')==raw
 row=json.loads(read_review_bytes(tmp_path,'events.part-0000.jsonl'))
 assert row['original_sequence']==7 and row['export_hash']==sha((tmp_path/row['large_record_ref']).read_bytes())
 assert json.loads(read_review_bytes(tmp_path,row['large_record_ref']))==payload
 assert b'actor=A request=R event=E' in out['trajectories/run/conversation.md']
 assert json.loads(read_review_bytes(tmp_path,note['conversation_payload_refs'][0]['payload_ref']))==payload
 assert b'evidence/a.json.gz' in out['README.md'] and note['duplicate_files']
 assert pack_review_files(files)[0]==out

def test_complete_export_auto_packs_within_limit_and_keeps_manifest_hashes(tmp_path):
 from trustfork.runtime.dynamic.artifacts import atomic_json
 from trustfork.runtime.dynamic.review_export import export_campaign
 source=tmp_path/'source';source.mkdir()
 atomic_json(source/'campaign.json',{'campaign_id':'fixture','status':'complete','identity':{'commit':'a'*40}})
 (source/'diagnostics').mkdir()
 atomic_json(source/'diagnostics'/'large.json',{'complete_text':'RISK_SYNTHETIC '*40000})
 out=tmp_path/'out';manifest=export_campaign(source,out,max_total_bytes=100000)
 assert manifest['packing']['gzip_files'] and manifest['size_bytes_excluding_manifest']<100000
 assert json.loads(read_review_bytes(out,'evidence/diagnostics/large.json.gz'))['complete_text']=='RISK_SYNTHETIC '*40000
 for row in manifest['files']:assert sha((out/row['path']).read_bytes())==row['export_hash']
 export_campaign(source,out,max_total_bytes=100000)

def test_xz_large_jsonl_is_deterministic_complete_and_hash_bound(tmp_path):
 raw=b"".join(canonical({"sequence":i,"event_id":str(i),"text":"independent occurrence "+("long context "*8000)})+b"\n" for i in range(50))
 files={"evidence/events.jsonl":raw,"README.md":b"[Events](evidence/events.jsonl)"}
 out,rename,note=pack_review_files(files)
 name=rename["evidence/events.jsonl"]
 assert name.endswith(".xz") and len(out[name])<len(raw)/100
 for n,data in out.items():
  p=tmp_path/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
 assert read_review_bytes(tmp_path,name)==raw and len(read_review_bytes(tmp_path,name).splitlines())==50
 assert note["xz_files"][0]["uncompressed_sha256"]==sha(raw)
 assert note["xz_files"][0]["stored_sha256"]==sha(out[name])
 assert name.encode() in out["README.md"] and pack_review_files(files)[0]==out
