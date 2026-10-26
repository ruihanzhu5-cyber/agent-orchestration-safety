"""One bounded continuation of an immutable campaign, using its original ledger."""
import copy,json,shutil
from pathlib import Path
from .common import DynamicError,read_json,file_hash,digest
from .artifacts import atomic_json,file_lock
from .campaign_budget import CampaignBudget
from .initial_plan import planning_identity
from trustfork.scoring.scoring_versions import frozen_identity
PARENT_ID="first-api-20261026"
SEGMENT_ID="plan-judge-followup-20261026"
BASELINE="e96d7abe0fcb95e3c539bba2eeaeec428c7b497a"
EXECUTION="6cfb3a34b95d14a4b35873b5068aba5dafa398b4"

def parent_sources(parent):
 parent=Path(parent).resolve()
 campaign=read_json(parent/"campaign.json")
 if campaign.get("campaign_id")!=PARENT_ID or campaign.get("identity",{}).get("commit")!=EXECUTION:raise DynamicError("followup_parent_identity_mismatch","Wrong original campaign/execution")
 status=read_json(parent/"diagnostics/smoke-status.json")
 runs=[r for r in status["runs"] if r.get("team_model")=="gpt4o" and r.get("run_id")]
 if len(runs)!=4 or {(r["protocol"],r["condition"]) for r in runs}!={("S","HP"),("S","HA"),("F","HP"),("F","HA")}:raise DynamicError("followup_parent_runs_missing","Exact four GPT runs required")
 files=["campaign.json","results.json","resolved-config.json","plan.jsonl","diagnostics/phase-started-probes.json","diagnostics/phase-started-smoke.json"]
 seal={"files":{name:file_hash(parent/name) for name in files},"runs":{r["run_id"]:{"path":r["path"],"frozen_identity":frozen_identity(r["path"])} for r in runs}}
 return seal,runs

class FollowupSegment:
 def __init__(self,parent,path,config,execution_sha):
  self.parent=Path(parent).resolve();self.path=Path(path).resolve()
  seal,self.runs=parent_sources(self.parent)
  budget=config["campaign_budget"];expected=self.parent/"campaign-budget.sqlite3"
  if Path(budget["path"]).resolve()!=expected or budget["campaign_id"]!=PARENT_ID:raise DynamicError("followup_original_budget_mismatch","Original campaign ledger required")
  self.identity={"parent_campaign_id":PARENT_ID,"parent_result_commit":BASELINE,"parent_execution_commit":EXECUTION,"source_seal":seal,
   "execution_code_sha":execution_sha,"planning_contract":planning_identity(),"config_hash":digest(config),"actual_judge_binding":config["judge_binding"],
   "actions":["formal_fixtures","rescore_old_gpt","new_deepseek_chain"],"budget_ledger_id":digest(str(expected)),"segment_ceiling_cny":20}
  self.path.mkdir(parents=True,exist_ok=True)
  with file_lock(self.path/".segment.lock"):
   p=self.path/"segment.json"
   if p.exists():
    if read_json(p)["identity"]!=self.identity:raise DynamicError("followup_segment_identity_mismatch","Do not reset or change a started continuation")
   else:atomic_json(p,{"segment_id":SEGMENT_ID,"identity":self.identity,"status":"prepared"})
  self.config=copy.deepcopy(config)
  self.config["campaign_budget"].update(must_exist=True,segment_id=SEGMENT_ID,segment_cny=20,segment_identity={"identity_hash":digest(self.identity)})
  self.budget=CampaignBudget(expected,campaign_id=PARENT_ID,must_exist=True,segment_id=SEGMENT_ID,segment_cny=20,segment_identity={"identity_hash":digest(self.identity)})
  self.verify_parent()

 def verify_parent(self):
  current,_=parent_sources(self.parent)
  if current!=self.identity["source_seal"]:raise DynamicError("followup_parent_changed","Original frozen source/markers changed")

 def action(self,name,fn):
  if name not in {"formal_fixtures","rescore_old_gpt","new_deepseek_chain"}:raise DynamicError("followup_action_unknown",name)
  with file_lock(self.path/".action.lock"):
   self.verify_parent();target=self.path/"actions"/(name+".json")
   if target.exists():
    previous=read_json(target)
    if previous["status"] in ("completed","blocked","failed"):return previous["result"]
    # A sender may have submitted before a crash. Do not infer it was never sent.
    return {"status":"blocked","reason":"interrupted_action_requires_reconciliation","action":name}
   atomic_json(target,{"status":"started","identity_hash":digest(self.identity),"budget_before":self.budget.summary(),"segment_before":self.budget.segment_summary()})
   try:result=fn()
   except (DynamicError,OSError,TimeoutError) as e:
    result={"status":"blocked","reason":getattr(e,"code",type(e).__name__),"error":str(e)}
   atomic_json(target,{"status":result.get("status","completed"),"identity_hash":digest(self.identity),"result":result,
    "budget_after":self.budget.summary(),"segment_after":self.budget.segment_summary()})
   self.verify_parent();return result

def clone_frozen_run(source,destination):
 """Copy exact raw records and old score versions; new scoring never edits the parent."""
 source=Path(source);dest=Path(destination)
 if dest.exists():raise DynamicError("followup_clone_exists","Reuse via recorded action state, never overwrite")
 before=frozen_identity(source);run=read_json(source);dest.mkdir(parents=True)
 for name in ("run.json",run["run_manifest_path"],run["events_path"],run["prefix_events_path"]):
  rel=Path(name)
  if rel.is_absolute() or ".." in rel.parts:raise DynamicError("followup_source_relative_path","Frozen record paths must stay in run directory")
  target=dest/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source.parent/rel,target)
 shutil.copytree(source.parent/"scoring",dest/"scoring")
 if frozen_identity(dest/"run.json")!=before:raise DynamicError("followup_clone_identity_mismatch","Copied raw record differs")
 atomic_json(dest/"origin.json",{"source_run":str(source),"source_frozen_identity":before,"run_id":run["run_id"],"behavior_execution_sha":EXECUTION,"new_behavior_requests":0})
 if frozen_identity(source)!=before:raise DynamicError("followup_parent_changed","Source changed while copying")
 return dest/"run.json"
