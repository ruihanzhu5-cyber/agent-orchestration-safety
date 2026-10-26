import json
from types import SimpleNamespace
import pytest
from test_provider_preparation import configuration
from trustfork.tools.first_dynamic_api import judge_candidate
from trustfork.runtime.dynamic.first_api_plan import judge_probe_cases
@pytest.mark.parametrize("team",["gpt4o","deepseekflash"])
def test_original_candidate_repairs_keep_full_content_and_own_reasoning(tmp_path,monkeypatch,team):
 import trustfork.tools.first_dynamic_api as module
 cases={c["case_id"]:c for c in judge_probe_cases()};sent=[]
 long="INVALID_SCORE"*900;reason="OWN_JUDGE_REASONING"*400
 class MockOnly:
  count=0
  campaign=SimpleNamespace(rows=lambda:[])
  def request(self,alias,wire,*,request_id,**kwargs):
   self.count+=1;body=json.loads(wire["body"]);sent.append(body)
   case=json.loads(body["messages"][1]["content"]);original=cases[case["case_id"]]
   if request_id.endswith("-0"):content=long
   else:content=json.dumps({"case_id":case["case_id"],"facts":{k:{"value":v,"evidence_refs":original["required_refs"][k]} for k,v in original["expected"].items()}})
   return {"status":200,"headers":{},"body":json.dumps({"choices":[{"finish_reason":"stop","message":{"content":content,"reasoning_content":reason}}]})}
 mock=MockOnly();monkeypatch.setattr(module,"transport",lambda *a,**k:mock)
 c=configuration()
 if team=="deepseekflash":c["logical_bindings"][team].update(thinking="enabled",reasoning_effort="high")
 result=judge_candidate(c,tmp_path,team)
 assert result["critical_pass"] and mock.count==10
 for body in sent[1::2]:
  prior=body["messages"][-2]
  assert prior["content"]==long
  if team=="deepseekflash":assert prior["reasoning_content"]==reason
