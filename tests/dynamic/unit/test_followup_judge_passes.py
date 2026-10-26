import json,copy
import pytest
from test_provider_preparation import configuration
from test_first_api_judge import reply,unknown_result
from trustfork.runtime.dynamic.common import write_json,DynamicError,read_json
from trustfork.scoring.dynamic_adapter import trajectory_judge_view
from trustfork.tools.judge_dynamic import run_judge_attempt

def setup(tmp_path,monkeypatch):
 import trustfork.tools.judge_dynamic as module
 import trustfork.scoring.goal_observer as goal
 monkeypatch.setattr(module,"load_events",lambda *a:[])
 monkeypatch.setattr(module,"extract_formal_deliverables",lambda *a,**k:[{"deliverable_id":"d"}])
 monkeypatch.setattr(goal,"frozen_workspace",lambda *a:{"evidence_ref":"state://fixture","paths":{}})
 run=tmp_path/"run.json";write_json(run,{"case_id":"p001","run_id":"fixed","q":"C","prefix_export":{},"frozen_export":{}})
 write_json(tmp_path/"scoring/response_input.json",{"data":{"responses":[{"response_id":"d","text":"a genuine fixture delivery"}]}})
 view=trajectory_judge_view([],task={},private_goals={},frozen_state={},final_response="")
 write_json(tmp_path/"scoring/trajectory_input.json",{"data":view})
 c=configuration()
 import importlib.metadata
 for b in c["logical_bindings"].values():
  b["capability"]["tokenizer"].update(id="o200k_base",version=importlib.metadata.version("tiktoken"),count_method="local-message-content-and-schema-bpe-estimate")
 scorer={"response_output_budget_tokens":128,"trajectory_output_budget_tokens":999999,"trajectory_representation":"legacy-full"}
 response=reply(json.dumps({"response_judgements":{"d":{"rtf":0,"rsr":0,"status":"complete","evidence_refs":["response://d"]}}}))
 return run,c,scorer,{"response":response}

def test_independent_response_survives_trajectory_capacity_block(tmp_path,monkeypatch):
 run,c,s,replies=setup(tmp_path,monkeypatch)
 result=run_judge_attempt(run,tmp_path/"attempt",c,mode="mock",scorer_config=s,mock_replies=replies)
 assert result["pass_states"]["response"]["status"]=="completed"
 assert result["pass_states"]["trajectory"]["status"]=="blocked"
 assert result["judge_attempts"]==1 and result["status"]=="partial"
 assert read_json(tmp_path/"attempt/response-result.json")["result"]["response_judgements"]["d"]["rtf"]==0
 assert read_json(tmp_path/"attempt/scoring_annotations.json")["trajectory_judgements"]=={}

def test_first_single_pass_pending_and_explicit_success_reuse(tmp_path,monkeypatch):
 run,c,s,replies=setup(tmp_path,monkeypatch)
 first=run_judge_attempt(run,tmp_path/"first",c,mode="mock",scorer_config=s,mock_replies=replies,passes=("response",))
 assert first["judge_attempts"]==1 and first["pass_states"]["trajectory"]["status"]=="pending"
 second=run_judge_attempt(run,tmp_path/"second",c,mode="mock",scorer_config=s,mock_replies={},prior_attempt=tmp_path/"first")
 assert second["judge_attempts"]==0 and second["pass_states"]["response"]["reused"] is True
 changed=copy.deepcopy(s);changed["response_output_budget_tokens"]=129
 with pytest.raises(DynamicError,match="judge_prior_pass_mismatch"):
  run_judge_attempt(run,tmp_path/"wrong",c,mode="mock",scorer_config=changed,mock_replies={},prior_attempt=tmp_path/"first")

def test_full_previous_judge_answer_enters_one_repair_and_overflow_never_sends(tmp_path):
 from trustfork.runtime.dynamic.provider import ProviderTransport
 from trustfork.scoring.judge_request import prepare_judge_request
 from trustfork.scoring.judge_client import JudgeClient
 from collections import deque
 c=configuration();long="INVALID"*1600
 replies=deque([reply(long),reply(json.dumps(unknown_result()))]);sent=[]
 def http(u,b,*a):sent.append(json.loads(b));return replies.popleft()
 t=ProviderTransport(c,mode="mock",journal=tmp_path/"j.jsonl",http=http,kind="judge",max_requests=2)
 p=prepare_judge_request({},rubric="same",format_instructions="JSON",output_budget=100,counter=len,judge_binding=c["logical_bindings"]["gpt4o"])
 JudgeClient(t).send_with_repair(p,request_id="j",pass_name="trajectory")
 assert sent[1]["messages"][-2]["content"]==long
 c["logical_bindings"]["gpt4o"]["capability"]["effective_context_tokens"]=2000
 t2=ProviderTransport(c,mode="mock",journal=tmp_path/"blocked.jsonl",http=lambda *a:reply(long),kind="judge",max_requests=2)
 with pytest.raises(DynamicError,match="repair_input_overflow"):JudgeClient(t2).send_with_repair(p,request_id="k",pass_name="trajectory")
 assert t2.count==1

def test_completed_response_reuse_survives_other_pass_output_calibration(tmp_path,monkeypatch):
 run,c,s,replies=setup(tmp_path,monkeypatch)
 first=run_judge_attempt(run,tmp_path/"first",c,mode="mock",scorer_config=s,mock_replies=replies,passes=("response",))
 changed=copy.deepcopy(s);changed["trajectory_output_budget_tokens"]*=2
 again=run_judge_attempt(run,tmp_path/"calibrated",c,mode="mock",scorer_config=changed,mock_replies={},prior_attempt=tmp_path/"first")
 assert again["judge_attempts"]==0 and again["pass_states"]["response"]["reused"]

def test_long_thinking_repair_keeps_its_own_full_reasoning_and_content(tmp_path):
 from collections import deque
 from trustfork.runtime.dynamic.provider import ProviderTransport
 from trustfork.scoring.judge_request import prepare_judge_pass
 from trustfork.scoring.judge_client import JudgeClient
 from test_first_api_judge import reply,unknown_result
 c=configuration();c["judge_binding"]="deepseekflash";b=c["logical_bindings"]["deepseekflash"]
 b.update(thinking="enabled",reasoning_effort="high");b["supported_parameters"]+=["thinking","reasoning_effort"]
 bundle={"views":{"trajectory":{"frozen":"same"}},"prompts":{"trajectory":"rubric"},"formats":{"trajectory":"JSON"},"builder_version":"fixture","scoring_profile":"legacy-eight-v1","sanitizer":{},"response_ids":[]}
 p=prepare_judge_pass(bundle,"trajectory",binding=b,scorer_config={"trajectory_representation":"legacy-full","trajectory_output_budget_tokens":100},counter=len)
 content="INVALID"*1200;reasoning="OWN_REASONING"*1000;sent=[]
 replies=deque([reply(content,reasoning=reasoning),reply(json.dumps(unknown_result()))])
 def http(u,body,*a):sent.append(json.loads(body));return replies.popleft()
 t=ProviderTransport(c,mode="mock",journal=tmp_path/"requests.jsonl",http=http,max_requests=2,kind="judge")
 JudgeClient(t).send_with_repair(p,request_id="own",pass_name="trajectory")
 assert sent[1]["messages"][-2]=={"role":"assistant","content":content,"reasoning_content":reasoning}
 assert t.accounting(b,sent[1])["components"]["reasoning"]==len(reasoning)
