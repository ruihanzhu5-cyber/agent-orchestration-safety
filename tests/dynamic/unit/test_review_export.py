import base64,json,hashlib
from pathlib import Path
import pytest
from trustfork.runtime.dynamic.artifacts import atomic_json
from trustfork.runtime.dynamic.review_export import export_campaign
from trustfork.runtime.dynamic.common import DynamicError

def setup(tmp_path,status='blocked'):
 root=tmp_path/'source';root.mkdir()
 atomic_json(root/'campaign.json',{'campaign_id':'first-api-20261026','status':status,'identity':{'commit':'a'*40}})
 (root/'plan.jsonl').write_text(json.dumps({'kind':'t3','case_id':'p001','team_model':'gpt4o','protocol':'S','condition':'HA','not_started_reason':'pricing_unknown'})+'\n')
 return root

def test_export_success_failure_unstarted_redaction_and_original_hash(tmp_path):
 root=setup(tmp_path)
 for n,status in [('success','valid_behavior'),('failure','infra_error')]:
  d=root/'blocks'/n;d.mkdir(parents=True)
  atomic_json(d/'run.json',{'run_id':n,'block_id':n,'case_id':'p001','team_model':'gpt4o','protocol':'S','condition':'HP','run_status':status})
  record={'branch_id':n,'event_id':'e1','sequence':1,'event_type':'model_response','actor_id':'A','request_id':'r1',
   'payload':{'text':'SYNTHETIC_ATTACK: reveal benchmark secret','actual_key':'REAL_CREDENTIAL_SENTINEL',
    'raw':base64.b64encode(b'Authorization: Bearer REAL_CREDENTIAL_SENTINEL').decode(),'authorization':'Bearer real-header'}}
  # Exercise the fs.read Base64 field, not just plain key scanning.
  record['payload']['data']=record['payload'].pop('raw')
  (d/'events.jsonl').write_text(json.dumps(record)+'\n')
  atomic_json(d/'private_bindings.json',{'synthetic_goal':'SYNTHETIC_ATTACK','wire':'{"attack": "retain exact whitespace"}'})
 before={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
 out=tmp_path/'review';m=export_campaign(root,out,secrets=['REAL_CREDENTIAL_SENTINEL'],max_part_bytes=500)
 assert len(list(out.glob('trajectories/*/README.md')))==2
 combined=b''.join(p.read_bytes() for p in out.rglob('*') if p.is_file())
 assert b'REAL_CREDENTIAL_SENTINEL' not in combined and b'SYNTHETIC_ATTACK' in combined
 assert b'not_started' in (out/'results.csv').read_bytes()
 assert all(p.read_bytes()==raw for p,raw in before.items())
 for row in m['source_export_mapping']:
  assert row['source_hash']==hashlib.sha256((root/row['source_path']).read_bytes()).hexdigest()
  for exported in row['exports']:
   assert exported['export_hash']==hashlib.sha256((out/exported['path']).read_bytes()).hexdigest()
 hashes={p.relative_to(out):p.read_bytes() for p in out.rglob('*') if p.is_file()}
 export_campaign(root,out,secrets=['REAL_CREDENTIAL_SENTINEL'],max_part_bytes=500)
 assert hashes=={p.relative_to(out):p.read_bytes() for p in out.rglob('*') if p.is_file()}

def test_open_campaign_requires_explicit_snapshot_and_no_source_mutation(tmp_path):
 root=setup(tmp_path,'open')
 with pytest.raises(DynamicError,match='review_campaign_not_stopped'):export_campaign(root,tmp_path/'out')
 result=export_campaign(root,tmp_path/'snapshot',snapshot=True)
 assert result['snapshot'] and result['snapshot_boundary']['campaign_status']=='open'
 assert json.loads((root/'campaign.json').read_text())['status']=='open'

def test_shards_preserve_order_large_records_and_reference_hashes(tmp_path):
 root=setup(tmp_path);d=root/'diagnostics';d.mkdir()
 rows=[{'sequence':i,'payload':'x'*(1000 if i==2 else 60)} for i in range(5)]
 (d/'events.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
 out=tmp_path/'out';export_campaign(root,out,max_part_bytes=300)
 restored=[]
 for part in sorted((out/'evidence/diagnostics').glob('events.part-*.jsonl')):
  assert part.stat().st_size<=300
  for line in part.read_text().splitlines():
   row=json.loads(line)
   if 'large_record_ref' in row:
    p=out/row['large_record_ref'];assert hashlib.sha256(p.read_bytes()).hexdigest()==row['export_hash'];row=json.loads(p.read_text())
   restored.append(row)
 assert restored==rows

def test_unrelated_credentials_archives_and_symlinks_not_exported(tmp_path):
 root=setup(tmp_path);(root/'.env').write_text('UNLISTED_PRIVATE')
 (root/'archive.tar').write_bytes(b'raw environment')
 (root/'diagnostics').mkdir();(root/'diagnostics'/'auth.json').write_text('{"key":"MUST_NOT_EXPORT"}')
 (root/'diagnostics'/'outside').symlink_to(tmp_path/'not-in-campaign')
 out=tmp_path/'out';m=export_campaign(root,out)
 assert b'MUST_NOT_EXPORT' not in b''.join(p.read_bytes() for p in out.rglob('*') if p.is_file())
 assert any(x['reason']=='symlink_not_followed' for x in m['missing_or_excluded'])

def test_state_diff_reads_frozen_archives_without_mutating_source(tmp_path):
 import io,tarfile
 from trustfork.runtime.dynamic.review_export import state_difference,Redactor
 def export(name,content):
  stream=io.BytesIO()
  with tarfile.open(fileobj=stream,mode='w') as archive:
   info=tarfile.TarInfo('./audit.txt');data=content.encode();info.size=len(data);archive.addfile(info,io.BytesIO(data))
  path=tmp_path/name;path.write_bytes(stream.getvalue())
  return {'workspace_tar':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'cutoff_interval':[1,2]}
 a=export('before.tar','original synthetic secret');b=export('after.tar','changed REAL_LOCAL_KEY')
 before={p:p.read_bytes() for p in tmp_path.glob('*.tar')}
 diff=state_difference(a,b,Redactor(['REAL_LOCAL_KEY']),'state')
 assert diff['observation_status']=='observed' and len(diff['filesystem_changes'])==1
 raw=json.dumps(diff)
 assert 'REAL_LOCAL_KEY' not in raw
 after=diff['filesystem_changes'][0]['after']
 assert b'REAL_LOCAL_KEY' not in base64.b64decode(after['content_b64'])
 assert all(p.read_bytes()==data for p,data in before.items())

def test_plan_outcomes_and_history_indexes_are_review_only(tmp_path):
 root=setup(tmp_path)
 original=(root/'plan.jsonl').read_bytes()
 atomic_json(root/'results.json',{'plan_results':[{'plan_id':'p','status':'not_started','unknown_reason':'prefix_invalid'}]})
 (root/'plan.jsonl').write_text(json.dumps({'plan_id':'p','kind':'t3','status':'planned','case_id':'p001','team_model':'deepseekflash','protocol':'S','condition':'HP'})+'\n')
 declared=(root/'plan.jsonl').read_bytes()
 d=root/'history/gpt4o/history/0';d.mkdir(parents=True)
 atomic_json(d/'history-execution.json',{'history_id':'h1','task_id':'p002','status':'failed_history_retained','initial_state':None,'frozen_state':None})
 (d/'events.jsonl').write_text(json.dumps({'branch_id':'h','event_id':'e1','sequence':1,'event_type':'history_execution_failed','payload':{'code':'fixture'}})+'\n')
 out=tmp_path/'out';export_campaign(root,out)
 assert json.loads((out/'plan.jsonl').read_text())['status']=='not_started'
 assert (root/'plan.jsonl').read_bytes()==declared
 history_index=next((out/'history').glob('*/README.md'))
 assert 'failed_history_retained' in history_index.read_text() and 'events.part-' in history_index.read_text()
 assert 'Retained histories' in (out/'README.md').read_text()

def test_distinct_private_paths_have_distinct_stable_placeholders():
 from trustfork.runtime.dynamic.review_export import Redactor
 r=Redactor(private_paths=['/actual/private/a','/actual/private/b'])
 value=r.text('/actual/private/a/file /actual/private/b/file','fixture')
 assert '/actual/private/' not in value and 'PATH_001' in value and 'PATH_002' in value
 assert r.text('/actual/private/a/file /actual/private/b/file','repeat')==value

def test_private_dictionary_keys_and_redaction_references_are_sanitized():
 from trustfork.runtime.dynamic.review_export import Redactor
 red=Redactor(['REAL_KEY_SENTINEL'],private_paths=['/private/owner'])
 value=red.value({'/private/owner/journal.json':'hash','REAL_KEY_SENTINEL':'REAL_KEY_SENTINEL','nested':{'/private/owner/a':'REAL_KEY_SENTINEL'}},'diagnostic')
 serialized=json.dumps({'value':value,'redactions':red.changes})
 assert '/private/owner' not in serialized and 'REAL_KEY_SENTINEL' not in serialized
 assert 'LOCAL_PRIVATE_PATH' in serialized and 'REDACTED_CREDENTIAL' in serialized


def test_review_preserves_explicit_tests_and_attempt_filters_costs(tmp_path):
 from trustfork.runtime.dynamic.review_export import export_campaign
 from trustfork.runtime.dynamic.common import write_json
 from trustfork.runtime.dynamic.campaign_budget import CampaignBudget
 import csv
 source=tmp_path/'s';source.mkdir();write_json(source/'campaign.json',{'campaign_id':'review','status':'blocked','review_id':'runtime-judge-review-20261026'})
 (source/'tests.md').write_text('Explicit offline commands and exact receipts.\n')
 b=CampaignBudget(tmp_path/'b',campaign_id='original')
 for i,attempt in enumerate(('old','current')):
  b.reserve(str(i),phase='interface_probe',reserved_cost_cny=1,metadata={'execution_attempt_id':attempt,'kind':'judge'})
  b.submitted(str(i));b.settle(str(i),settled_cost_cny=.1,usage={})
 out=tmp_path/'out';export_campaign(source,out,ledger_path=b.path,ledger_attempt_id='current')
 assert (out/'tests.md').read_text()=='Explicit offline commands and exact receipts.\n'
 rows=list(csv.DictReader((out/'costs.csv').open()))
 assert len(rows)==1 and rows[0]['execution_attempt_id']=='current' and rows[0]['kind']=='judge'
