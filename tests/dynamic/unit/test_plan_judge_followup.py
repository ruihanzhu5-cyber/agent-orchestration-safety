import copy,json
import pytest
from trustfork.runtime.dynamic.common import DynamicError,digest
from trustfork.runtime.dynamic.initial_plan import planning_contract,parse_initial_plan,planning_identity

def plan(refs=(),text="Inspect /workspace/contact.md"):
 return json.dumps({"plan_status":"delegate","assignments":[{"recipient":"A","task_text":text,"context_refs":list(refs)}],"draft_answer":None})

def test_registered_context_contract_and_filesystem_paths_are_distinct():
 c=planning_contract()
 assert c["contract_version"]=="initial-plan-v2"
 assert c["allowed_context_refs"]==["task://current-stage"]
 for refs in ([],c["allowed_context_refs"]):
  assert parse_initial_plan(plan(refs))["plan"]["assignments"][0]["task_text"]=="Inspect /workspace/contact.md"
 with pytest.raises(DynamicError) as e:parse_initial_plan(plan(["/workspace"]))
 assert e.value.code=="invalid_plan_context_reference"
 assert "/workspace" in str(e.value) and "task://current-stage" in str(e.value)
 assert planning_identity()["contract_hash"]==digest(c)
 c["allowed_context_refs"].append("/workspace")
 assert "/workspace" not in planning_contract()["allowed_context_refs"]

@pytest.mark.parametrize("status",["refusal","no_plan","answer_ready"])
def test_non_delegating_intent_is_not_filled(status):
 p=parse_initial_plan(json.dumps({"plan_status":status,"assignments":[],"draft_answer":None}))["plan"]
 assert p["plan_status"]==status and p["assignments"]==[]

def test_invalid_semantic_reference_does_not_trigger_format_repair():
 calls=[]
 with pytest.raises(DynamicError,match="invalid_plan_context_reference"):
  parse_initial_plan(plan(["/workspace"]),repair=lambda *a:calls.append(a))
 assert calls==[]

def test_actual_planning_packet_uses_shared_contract_and_keeps_workspace():
 from types import SimpleNamespace
 from trustfork.agents.pi_dynamic import PiDynamic
 r=PiDynamic("p001","/tmp/trustfork-packet-contract-fixture")
 r.lifecycle=SimpleNamespace(epoch=0,state="PLANNING")
 r.mailbox=SimpleNamespace(claim=lambda *a,**k:[])
 r.membership=SimpleNamespace(directory=lambda:[])
 r.profile_service=None
 packet=r._packet("Main","req",None)
 assert packet["planning_contract"]==planning_contract()
 assert packet["workspace_root"]=="/workspace"
 assert parse_initial_plan(plan(packet["planning_contract"]["allowed_context_refs"]))["plan"]["assignments"]
 packet["planning_contract"]["allowed_context_refs"].append("/workspace")
 assert "/workspace" not in planning_contract()["allowed_context_refs"]

def test_contract_identity_binds_history_and_prefix(tmp_path,monkeypatch):
 from trustfork.agents.pi_dynamic import PiDynamic
 from trustfork.runtime.dynamic.prepared_artifacts import history_contract
 import trustfork.agents.pi_dynamic as controller
 import trustfork.runtime.dynamic.initial_plan as module
 r=PiDynamic("p001",tmp_path/"runtime")
 before_history=history_contract(r);before_prefix=r.prefix_identity()
 altered={**planning_identity(),"contract_hash":"future-contract"}
 monkeypatch.setattr(module,"planning_identity",lambda:altered)
 monkeypatch.setattr(controller,"planning_identity",lambda:altered)
 assert history_contract(r)!=before_history
 assert r.prefix_identity()!=before_prefix
