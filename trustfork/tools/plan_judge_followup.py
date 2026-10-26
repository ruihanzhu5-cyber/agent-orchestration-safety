"""Fixed 2026-10-26 continuation: formal fixtures, frozen GPT rescoring, DeepSeek chain."""
import argparse,copy,json,os,subprocess
from pathlib import Path
from trustfork.runtime.dynamic.common import DynamicError,read_json,write_json,digest,file_hash,repo_root
from trustfork.runtime.dynamic.artifacts import artifact_root,atomic_json
from trustfork.runtime.dynamic.followup import FollowupSegment,SEGMENT_ID,BASELINE,clone_frozen_run
from trustfork.runtime.dynamic.provider import ProviderTransport
from trustfork.scoring.judge_request import prepare_judge_pass
from trustfork.scoring.judge_client import JudgeClient
from trustfork.scoring.formal_judge_fixtures import make_fixture,check_fixture
from trustfork.scoring.trajectory_observer import event_ref
from trustfork.tools.judge_dynamic import run_judge_attempt
from trustfork.scoring.dynamic_pipeline import score_run
from trustfork.scoring.scoring_versions import rescore_contract

def judge_config(segment,phase):
 c=copy.deepcopy(segment.config);c["campaign_budget"]["phase"]=phase
 return c

def scorer(representation="trajectory-lossless-v2"):
 return {"scoring_profile":"dynamic-homogeneous-v2","judge_binding":"deepseekflash","temperature":None,
  "response_output_budget_tokens":16384,"trajectory_output_budget_tokens":65536,
  "trajectory_representation":representation,"execution_scope":"engineering_smoke"}

def formal_fixtures(segment):
 root=segment.path/"fixtures";results=[]
 c=judge_config(segment,"interface_probe");binding=c["logical_bindings"][c["judge_binding"]]
 for kind in ("direct_failed_attempt","chain_rejection_missing"):
  directory=root/kind;directory.mkdir(parents=True,exist_ok=False)
  fixture=make_fixture(directory,kind);write_json(directory/"source.json",fixture)
  # oracle remains a separate local/source record, never part of fixture['bundle'].
  for representation in ("trajectory-lossless-v1","trajectory-lossless-v2"):
   out=directory/representation
   prepared=prepare_judge_pass(fixture["bundle"],"trajectory",binding=binding,scorer_config={**scorer(representation),"trajectory_output_budget_tokens":16384})
   write_json(out/"prepared.json",prepared)
   t=ProviderTransport(c,mode="api",journal=out/"judge-requests.jsonl",authorize_real=True,kind="judge",max_requests=2)
   try:
    result=JudgeClient(t).send_with_repair({**prepared,"behavior_run_id":"formal-fixture-"+kind},request_id="followup-fixture-"+kind+"-"+representation,pass_name="trajectory",evidence_refs={event_ref(e) for e in fixture["events"]})
    write_json(out/"result.json",result);checked=check_fixture(fixture,result["result"]);write_json(out/"fact-check.json",checked)
    row={"fixture_id":kind,"representation":representation,"passed":checked["passed"],"checks":checked["checks"],"requests":t.count,"source_hash":fixture["source_hash"]}
   except (DynamicError,OSError,TimeoutError) as e:
    row={"fixture_id":kind,"representation":representation,"passed":False,"reason":getattr(e,"code",type(e).__name__),"requests":t.count,"source_hash":fixture["source_hash"]}
    write_json(out/"error.json",{"error":str(e),**row})
   results.append(row)
   print(json.dumps({"phase":"formal_fixture",**row}),flush=True)
 value={"status":"completed" if all(r["passed"] for r in results) else "blocked","passed":all(r["passed"] for r in results),"cases":results}
 write_json(root/"summary.json",value);return value

def accepted_judge(segment):
 p=segment.path/"fixtures/summary.json"
 return p.exists() and read_json(p).get("passed") is True

def score_frozen(segment,path,out):
 cfg=judge_config(segment,"engineering_smoke")
 attempt=run_judge_attempt(path,out,cfg,mode="api",scorer_config=scorer(),max_requests=4,authorize_real=True)
 # One explicitly authorized output-limit calibration on identical frozen evidence.
 # A local preflight may still block the larger complete output reserve.
 if attempt["pass_states"]["trajectory"]["status"]=="failed":
  responses=[]
  journal=out/"judge-requests.jsonl"
  if journal.exists():
   for line in journal.read_text().splitlines():
    entry=json.loads(line)
    if entry.get("status")!="response":continue
    try:responses.append(json.loads(entry["response"]["body"])["choices"][0]["finish_reason"])
    except (ValueError,KeyError,IndexError,TypeError):continue
  if responses and responses[-1]=="length":
   first=out;out=out.with_name(out.name+"-output-calibration1");sc=scorer()
   sc["trajectory_output_budget_tokens"]=min(2*sc["trajectory_output_budget_tokens"],cfg["logical_bindings"]["deepseekflash"]["max_output_tokens"])
   write_json(out.with_name(out.name+"-reason.json"),{"reason":"actual_judge_finish_length","first_attempt":str(first),"factor":2,"max_calibrations":1,"source_run_hash":file_hash(path)})
   attempt=run_judge_attempt(path,out,cfg,mode="api",scorer_config=sc,max_requests=2,authorize_real=True,passes=("trajectory",),prior_attempt=first)
   attempt["output_calibration_of"]=str(first)
 contract=rescore_contract(path,reason="Authorized bounded follow-up; exact frozen behavior, new independent Judge attempt",annotation_policy="new",new_annotations=out/"scoring_annotations.json")
 summary=score_run(path,mode="engineering-smoke",rescore=contract)
 return {"attempt":attempt,"scores":summary["scores"],"process_annotation_status":summary.get("process_annotation_status"),"run_id":read_json(path)["run_id"],"path":str(path),"scoring_execution_sha":segment.identity["execution_code_sha"]}

def rescore_gpt(segment):
 if not accepted_judge(segment):return {"status":"blocked","reason":"formal_judge_fixture_gate"}
 results=[]
 for row in segment.runs:
  dest=segment.path/"gpt-rescore"/(row["protocol"]+"-"+row["condition"])
  path=clone_frozen_run(row["path"],dest);out=dest/"judge-followup"
  try:result=score_frozen(segment,path,out);result.update(protocol=row["protocol"],condition=row["condition"])
  except (DynamicError,OSError,TimeoutError) as e:result={"run_id":row["run_id"],"protocol":row["protocol"],"condition":row["condition"],"status":"failed","reason":getattr(e,"code",type(e).__name__),"error":str(e),"path":str(path)}
  results.append(result);write_json(segment.path/"gpt-rescore/results.json",{"results":results})
  print(json.dumps({"phase":"rescore_gpt","protocol":row["protocol"],"condition":row["condition"],"pass_states":{k:v["status"] for k,v in result.get("attempt",{}).get("pass_states",{}).items()},"reason":result.get("reason")}),flush=True)
 done=all(r.get("attempt",{}).get("status")=="completed" for r in results)
 return {"status":"completed" if done else "blocked","results":results,"new_team_model_requests":0,"bounded_actions_finished":True}

def deepseek_chain(segment):
 from trustfork.agents.pi_dynamic import PiDynamic,ProviderSource
 from trustfork.runtime.dynamic.prepared_artifacts import prepare_history,load_history,save_prefix
 from trustfork.tools.first_dynamic_api import transport
 cfg=judge_config(segment,"engineering_smoke");root=segment.path/"deepseek";results=[]
 hout=root/"history";t=transport(cfg,hout,team="deepseekflash",limit=240)
 r=PiDynamic("p001",hout,provider=t,team_model="deepseekflash");hpath=hout/"history-bundle.json"
 try:
  bundle=prepare_history(r,ProviderSource(),hpath)
 except (DynamicError,OSError,TimeoutError) as e:return {"status":"blocked","reason":getattr(e,"code",type(e).__name__),"history_path":str(hout)}
 hist={"task_statuses":bundle["task_statuses"],"path":str(hpath),"history_bundle_id":bundle["bundle_id"]}
 engineering_failure=any(x=="failed_history_retained" for x in bundle["task_statuses"].values())
 for protocol in ("S","F"):
  if engineering_failure:
   results.extend({"protocol":protocol,"condition":condition,"status":"not_started","reason":"history_engineering_failure"} for condition in ("HP","HA"));continue
  out=root/"blocks"/protocol;t=transport(cfg,out,team="deepseekflash",limit=240)
  r=PiDynamic("p001",out,provider=t,team_model="deepseekflash",protocol=protocol)
  history=load_history(r,hpath)
  try:prefix=r.run_prefix(ProviderSource(),history=history)
  except (DynamicError,OSError,TimeoutError) as e:
   results.extend({"protocol":protocol,"condition":condition,"status":"not_started","reason":getattr(e,"code",type(e).__name__)} for condition in ("HP","HA"));continue
  if prefix["status"]!="triggered":
   results.extend({"protocol":protocol,"condition":condition,"status":"not_started","reason":"prefix_"+prefix["status"]} for condition in ("HP","HA"));continue
  save_prefix(r,prefix,out/"prepared-prefix.json")
  for condition in ("HP","HA"):
   try:
    run=r.run_branch(prefix["checkpoint"],condition,ProviderSource(),attempt=0);path=r.directory/"run.json"
    result={"protocol":protocol,"condition":condition,"status":run["run_status"],"run_id":run["run_id"],"path":str(path)}
    score_run(path,mode="engineering-smoke")
    if accepted_judge(segment):result["judging"]=score_frozen(segment,path,path.parent/"judge-followup")
    else:result["judging"]={"status":"blocked","reason":"formal_judge_fixture_gate"}
   except (DynamicError,OSError,TimeoutError) as e:result={"protocol":protocol,"condition":condition,"status":"failed","reason":getattr(e,"code",type(e).__name__),"path":str(r.directory/"run.json")}
   results.append(result);write_json(root/"results.json",{"history":hist,"results":results})
   print(json.dumps({"phase":"deepseek_t3","protocol":protocol,"condition":condition,"status":result["status"],"remaining_segment_cny":segment.budget.segment_summary()["remaining_cny"]}),flush=True)
 done=not engineering_failure and len(results)==4 and all(r.get("status")=="valid_behavior" and r.get("judging",{}).get("attempt",{}).get("status")=="completed" for r in results)
 value={"status":"completed" if done else "blocked","history":hist,"results":results,"bounded_actions_finished":True};write_json(root/"results.json",value);return value

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument("--bindings",type=Path,required=True);p.add_argument("--env-file",type=Path,required=True)
 p.add_argument("--parent",type=Path,required=True);p.add_argument("--out",type=Path,required=True);p.add_argument("--phase",choices=["fixtures","rescore","deepseek","all"],required=True);p.add_argument("--allow-real-api",action="store_true");a=p.parse_args()
 if not a.allow_real_api:p.error("Explicit real API authorization required")
 code=subprocess.check_output(["git","rev-parse","HEAD"],cwd=repo_root(),text=True).strip()
 if subprocess.run(["git","merge-base","--is-ancestor",BASELINE,code],cwd=repo_root()).returncode:raise DynamicError("followup_baseline_mismatch","Retain the valid result successor")
 if subprocess.run(["git","diff","--quiet","HEAD","--","trustfork","tests"],cwd=repo_root()).returncode or subprocess.check_output(["git","ls-files","--others","--exclude-standard","--","trustfork","tests"],cwd=repo_root(),text=True).strip():raise DynamicError("execution_source_dirty","Commit tested source before sender")
 acceptance=read_json(a.out/"offline-acceptance.json")
 if acceptance.get("status")!="passed" or acceptance.get("execution_code_sha")!=code:raise DynamicError("offline_acceptance_required","Retained tests must match execution SHA")
 c=read_json(a.bindings)
 if c.get("judge_binding")!="deepseekflash" or c["logical_bindings"]["deepseekflash"].get("engineering_counting")!="deepseek-v41-text-v1":raise DynamicError("followup_binding_mismatch","Exact tested DeepSeek Judge/tokenizer required")
 from dotenv import dotenv_values
 values=dotenv_values(a.env_file)
 b=c["logical_bindings"]["deepseekflash"];key=os.environ.get(b["key_env"]) or values.get(b["key_env"])
 if not key:raise DynamicError("missing_provider_credential","Configured DeepSeek credential missing")
 os.environ[b["key_env"]]=key
 segment=FollowupSegment(a.parent,a.out,c,code)
 for phase,name,fn in [("fixtures","formal_fixtures",formal_fixtures),("rescore","rescore_old_gpt",rescore_gpt),("deepseek","new_deepseek_chain",deepseek_chain)]:
  if a.phase in (phase,"all"):
   result=segment.action(name,lambda fn=fn:fn(segment))
   print(json.dumps({"phase":phase,"status":result["status"],"budget":segment.budget.summary(),"segment":segment.budget.segment_summary()}),flush=True)
 write_json(segment.path/"budget-summary.json",{"campaign":segment.budget.summary(),"segment":segment.budget.segment_summary()})
if __name__=="__main__":main()
