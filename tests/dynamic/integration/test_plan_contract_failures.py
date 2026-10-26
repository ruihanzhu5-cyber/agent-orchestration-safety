"""Actual Docker/Pi entry failures keep raw output and sessions; all replies are mock."""
import json,runpy
import pytest
from trustfork.runtime.dynamic.common import repo_root,read_json,DynamicError
from trustfork.runtime.dynamic.provider import ProviderTransport
from trustfork.agents.pi_dynamic import PiDynamic,ProviderSource
from trustfork.runtime.dynamic.history_execution import execute_task
from test_first_api_runtime import sse

@pytest.mark.parametrize("entry",["history","prefix"])
def test_invalid_context_never_executes_workers_and_retains_raw_failure(tmp_path,entry):
 c=runpy.run_path(str(repo_root()/"tests/dynamic/unit/test_provider_preparation.py"))["configuration"]()
 bad=json.dumps({"plan_status":"delegate","assignments":[{"recipient":"A","task_text":"Inspect /workspace/contact.md","context_refs":["/workspace"]}],"draft_answer":None})
 seen=[]
 def http(u,b,*a):
  body=json.loads(b);seen.append(body)
  packet=json.loads(next(m["content"] for m in reversed(body["messages"]) if m["role"]=="user"))
  assert packet["planning_contract"]["allowed_context_refs"]==["task://current-stage"]
  return sse({"content":bad})
 t=ProviderTransport(c,mode="mock",journal=tmp_path/"requests.jsonl",http=http,max_requests=2)
 r=PiDynamic("p002" if entry=="history" else "p001",tmp_path/"runtime",provider=t,history_task=entry=="history")
 if entry=="history":
  sessions,record=execute_task(r,ProviderSource(),None)
  assert record["status"]=="failed_history_retained" and set(sessions)=={"Main","A","B"}
 else:
  with pytest.raises(DynamicError,match="invalid_plan_context_reference"):r.run_prefix(ProviderSource())
  error=read_json(r.directory/"prefix-outcome.json")["reason"]
  assert error["code"]=="invalid_plan_context_reference" and "/workspace" in error["reason"] and "task://current-stage" in error["reason"]
 events=[json.loads(x) for x in (r.directory/"events.jsonl").read_text().splitlines()]
 assert len(seen)==1 and not any(e["actor_id"] in ("A","B") and e["event_type"] in ("model_request_submitted","tool_operation_started") for e in events)
 assert not any(e["event_type"]=="lifecycle" and e["payload"].get("to")=="PLAN_READY" for e in events)
 partial=read_json(r.directory/"partial-state.json")
 assert set(partial["sessions"])=={"Main","A","B"} and all(x["status"]=="observed" for x in partial["sessions"].values())
 assert any(bad==block.get("text") for e in events if e["event_type"]=="model_response" for block in e["payload"].get("response",{}).get("content",[]) if isinstance(block,dict))
