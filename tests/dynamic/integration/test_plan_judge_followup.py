"""Original Docker/Pi and local HTTP mocks; no real model requests."""
import json,runpy,importlib.metadata
from pathlib import Path
from trustfork.agents.pi_dynamic import PiDynamic,ProviderSource
from trustfork.runtime.dynamic.provider import ProviderTransport
from trustfork.runtime.dynamic.common import repo_root,read_json,digest
from trustfork.runtime.dynamic.initial_plan import planning_contract
from trustfork.runtime.dynamic.prepared_artifacts import prepare_history,load_history,save_prefix
from test_provider_history import MockHistory

def test_shared_contract_real_h1_h2_then_s_and_f_without_forced_recruitment(tmp_path):
 cfg=runpy.run_path(str(repo_root()/"tests/dynamic/unit/test_provider_preparation.py"))["configuration"]()
 for b in cfg["logical_bindings"].values():
  b["max_output_tokens"]=16384;b["capability"]["max_output_tokens"]=16384
  b["capability"]["tokenizer"].update(id="o200k_base",version=importlib.metadata.version("tiktoken"),count_method="local-message-content-and-schema-bpe-estimate")
 mock=MockHistory()
 transport=ProviderTransport(cfg,mode="mock",journal=tmp_path/"requests.jsonl",http=mock,max_requests=180)
 history_runtime=PiDynamic("p001",tmp_path/"history",provider=transport)
 hfile=tmp_path/"history/history-bundle.json"
 bundle=prepare_history(history_runtime,ProviderSource(),hfile)
 assert bundle["contract"]["planning_contract"]["contract_version"]=="initial-plan-v2"
 for status in bundle["task_statuses"].values():assert status=="completed_unjudged"
 for protocol in ("S","F"):
  r=PiDynamic("p001",tmp_path/protocol,provider=transport,protocol=protocol)
  history=load_history(r,hfile)
  prefix=r.run_prefix(ProviderSource(),history=history)
  assert prefix["status"]=="triggered"
  assert prefix["checkpoint"]["bindings"]["prefix_identity"]["planning_contract"]["contract_version"]=="initial-plan-v2"
  save_prefix(r,prefix,tmp_path/protocol/"prepared-prefix.json")
  result=r.run_branch(prefix["checkpoint"],"HP",ProviderSource(),attempt=0)
  assert result["run_status"]=="valid_behavior"
  events=[json.loads(x) for x in (r.directory/"events.jsonl").read_text().splitlines()]
  actors={e["actor_id"] for e in events if e["event_type"]=="model_request_submitted"}
  if protocol=="S":
   assert {"C","D"}<=actors
   # Existing admission is programmatic and both enter at the same PLAN_READY boundary.
   admits=[e for e in events if e["event_type"]=="members_admitted"]
   assert len(admits)==1 and set(admits[0]["payload"]["actor_ids"])=={"C","D"}
  else:assert not ({"C","D"}&actors)
  from trustfork.scoring.dynamic_pipeline import score_run
  score_run(r.directory/"run.json",mode="test-fixtures")
  from trustfork.runtime.dynamic.followup import clone_frozen_run
  from trustfork.scoring.scoring_versions import frozen_identity
  from trustfork.tools.judge_dynamic import run_judge_attempt
  from test_homogeneous_end_to_end import judge_replies
  before=frozen_identity(r.directory/"run.json")
  copied=clone_frozen_run(r.directory/"run.json",tmp_path/(protocol+"-rescore"))
  replies=judge_replies(result,events)
  scoring={"scoring_profile":"dynamic-homogeneous-v2","response_output_budget_tokens":256,"trajectory_output_budget_tokens":999999,"trajectory_representation":"trajectory-lossless-v2"}
  judged=run_judge_attempt(copied,tmp_path/(protocol+"-judge"),cfg,mode="mock",scorer_config=scoring,mock_replies=replies)
  assert judged["pass_states"]["trajectory"]["status"]=="blocked"
  assert judged["pass_states"]["response"]["status"] in ("completed","not_applicable")
  assert frozen_identity(r.directory/"run.json")==before and frozen_identity(copied)==before
  # The copy must reach final aggregation, not just preparation/transport.
  from trustfork.scoring.scoring_versions import rescore_contract
  from trustfork.runtime.dynamic.common import file_hash
  original_pointer=file_hash(r.directory/"scoring/current_version.json")
  contract=rescore_contract(copied,reason="Offline copied-source full aggregation regression",annotation_policy="new",new_annotations=tmp_path/(protocol+"-judge")/"scoring_annotations.json")
  summary=score_run(copied,mode="test-fixtures",rescore=contract)
  assert summary["run_id"]==result["run_id"]
  assert file_hash(r.directory/"scoring/current_version.json")==original_pointer
  assert frozen_identity(copied)==before


 for body in mock.seen:
  for m in body["messages"]:
   if m["role"]!="user":continue
   try:packet=json.loads(m["content"])
   except (ValueError,TypeError):continue
   if "planning_contract" in packet:
    assert packet["planning_contract"]==planning_contract()
    assert packet["workspace_root"]=="/workspace"
 assert transport.count>0
 assert all(json.loads(x)["source"]=="mock" for x in transport.journal.read_text().splitlines())
