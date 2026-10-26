import json
from pathlib import Path
from collections import deque
import pytest
from trustfork.runtime.dynamic.common import write_json,file_hash,DynamicError
from trustfork.runtime.dynamic.followup import clone_frozen_run
from trustfork.scoring.formal_judge_fixtures import make_fixture
from trustfork.scoring.judge_client import JudgeClient,validate_judge_result
from trustfork.scoring.judge_request import prepare_judge_request
from trustfork.runtime.dynamic.provider import ProviderTransport
from test_provider_preparation import configuration
from test_first_api_judge import reply,unknown_result

def test_copied_frozen_source_keeps_required_scoring_metadata(tmp_path,monkeypatch):
 import trustfork.runtime.dynamic.followup as module
 source=tmp_path/"source";source.mkdir()
 write_json(source/"run.json",{"run_id":"original","run_manifest_path":"manifest.json","events_path":"events.jsonl","prefix_events_path":"prefix-events.json"})
 for n in ("manifest.json","events.jsonl","prefix-events.json","private_bindings.json","profile_metadata.json","delivery_receipts.json"):write_json(source/n,{"synthetic_source":n})
 write_json(source/"scoring/current_version.json",{"version":"unchanged"})
 monkeypatch.setattr(module,"frozen_identity",lambda p:{"run_hash":file_hash(Path(p))})
 result=clone_frozen_run(source/"run.json",tmp_path/"copy")
 for name in ("private_bindings.json","profile_metadata.json","delivery_receipts.json"):
  assert (result.parent/name).is_file() and file_hash(result.parent/name)==file_hash(source/name)

def test_formal_prompt_spells_exact_anchor_value_keys(tmp_path):
 bundle=make_fixture(tmp_path,"direct_failed_attempt")["bundle"]
 text=bundle["formats"]["trajectory"]
 assert '"terminal_safety"' in text and '"task_utility"' in text and '"value"' in text
 assert "lineage_version" in text

def test_repair_explains_exact_failed_field_without_converting_answer(tmp_path):
 c=configuration();sent=[]
 bad=unknown_result();bad["trajectory_judgements"]["ias"]={"anchor":0,"status":"complete","evidence_refs":["observed"]}
 responses=deque([reply(json.dumps(bad)),reply(json.dumps(unknown_result()))])
 def http(u,body,*a):sent.append(json.loads(body));return responses.popleft()
 t=ProviderTransport(c,mode="mock",journal=tmp_path/"judge.jsonl",kind="judge",max_requests=2,http=http)
 p=prepare_judge_request({},rubric="rubric",format_instructions="JSON",output_budget=100,counter=len,judge_binding=c["logical_bindings"]["gpt4o"])
 JudgeClient(t).send_with_repair(p,request_id="exact-error",pass_name="trajectory",evidence_refs={"observed"})
 assert "ias.value" in sent[1]["messages"][-1]["content"]
 assert json.loads(sent[1]["messages"][-2]["content"])==bad

def test_anchor_alias_is_still_rejected():
 bad=unknown_result();bad["trajectory_judgements"]["ias"]={"anchor":0,"status":"complete","evidence_refs":["observed"]}
 with pytest.raises(DynamicError,match="invalid_anchor"):
  validate_judge_result(bad,pass_name="trajectory",response_ids=[],evidence_refs={"observed"})

def test_nonrun_event_export_streams_without_whole_file_text_load(tmp_path,monkeypatch):
 from trustfork.runtime.dynamic.review_export import export_campaign
 from trustfork.runtime.dynamic.common import canonical
 source=tmp_path/"source";source.mkdir()
 write_json(source/"campaign.json",{"status":"blocked","campaign_id":"streaming-fixture","identity":{"commit":"fixture"}})
 path=source/"deepseek/history/history/0/events.jsonl";path.parent.mkdir(parents=True)
 rows=[{"branch_id":"synthetic-history","event_id":str(i),"sequence":i,"payload":{"text":"完整保留🙂"+str(i)}} for i in range(1000)]
 path.write_bytes(b"".join(canonical(x)+b"\n" for x in rows))
 original=Path.read_text
 def guarded(p,*a,**k):
  if p==path:pytest.fail("Non-run JSONL must not be loaded as one text string")
  return original(p,*a,**k)
 monkeypatch.setattr(Path,"read_text",guarded)
 dest=tmp_path/"public";export_campaign(source,dest)
 shards=sorted((dest/"evidence/deepseek/history/history/0").glob("events.part-*.jsonl"))
 decoded=[json.loads(x) for shard in shards for x in shard.read_text().splitlines()]
 assert decoded==rows
