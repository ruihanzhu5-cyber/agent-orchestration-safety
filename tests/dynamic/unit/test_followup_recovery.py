import copy,json
from pathlib import Path
import pytest
from trustfork.runtime.dynamic.common import read_json,write_json,file_hash,DynamicError
from trustfork.runtime.dynamic.followup import FollowupSegment,PARENT_ID,EXECUTION
from trustfork.runtime.dynamic.campaign_budget import CampaignBudget
from test_campaign_budget import configured_campaign

def setup_parent(tmp_path,monkeypatch):
 import trustfork.runtime.dynamic.followup as module
 parent=tmp_path/"parent";parent.mkdir()
 write_json(parent/"campaign.json",{"campaign_id":PARENT_ID,"identity":{"commit":EXECUTION}})
 for name in ("results.json","resolved-config.json","plan.jsonl","diagnostics/phase-started-probes.json","diagnostics/phase-started-smoke.json"):write_json(parent/name,{"old":"immutable"})
 runs=[]
 for protocol in ("S","F"):
  for condition in ("HP","HA"):
   p=parent/(protocol+condition+".json");write_json(p,{"raw":"unchanged"})
   runs.append({"team_model":"gpt4o","protocol":protocol,"condition":condition,"run_id":protocol+condition,"path":str(p)})
 write_json(parent/"diagnostics/smoke-status.json",{"runs":runs})
 monkeypatch.setattr(module,"frozen_identity",lambda path:{"raw_hash":file_hash(Path(path))})
 budget=CampaignBudget(parent/"campaign-budget.sqlite3",campaign_id=PARENT_ID)
 budget.reserve("old",phase="engineering_smoke",reserved_cost_cny=4,metadata={});budget.submitted("old");budget.settle("old",settled_cost_cny=3.000897,usage={})
 c=configured_campaign(parent/"campaign-budget.sqlite3");c["judge_binding"]="deepseekflash"
 return parent,c

def test_resume_keeps_parent_budget_and_never_reexecutes_completed_or_uncertain_action(tmp_path,monkeypatch):
 parent,c=setup_parent(tmp_path,monkeypatch);segment=FollowupSegment(parent,tmp_path/"segment",c,"tested-sha")
 calls=[]
 result=segment.action("rescore_old_gpt",lambda:(calls.append("judge-only") or {"status":"completed","new_team_model_requests":0}))
 again=FollowupSegment(parent,tmp_path/"segment",c,"tested-sha")
 assert again.budget.summary()["settled_cny"]==3.000897 and again.budget.segment_summary()["remaining_cny"]==20
 again.action("rescore_old_gpt",lambda:pytest.fail("completed action must not call any provider"))
 assert calls==["judge-only"] and result["new_team_model_requests"]==0
 write_json(again.path/"actions/new_deepseek_chain.json",{"status":"started"})
 stopped=again.action("new_deepseek_chain",lambda:pytest.fail("unknown send must not replay"))
 assert stopped["reason"]=="interrupted_action_requires_reconciliation"

def test_wrong_parent_marker_sha_or_segment_identity_refuses_without_modification(tmp_path,monkeypatch):
 parent,c=setup_parent(tmp_path,monkeypatch);segment=FollowupSegment(parent,tmp_path/"segment",c,"sha")
 old=read_json(parent/"campaign.json")
 with pytest.raises(DynamicError,match="followup_segment_identity_mismatch"):FollowupSegment(parent,tmp_path/"segment",c,"other-code")
 write_json(parent/"diagnostics/phase-started-smoke.json",{"changed":"test"})
 with pytest.raises(DynamicError,match="followup_parent_changed"):segment.verify_parent()
 assert read_json(parent/"campaign.json")==old
 write_json(parent/"campaign.json",{"campaign_id":PARENT_ID,"identity":{"commit":"wrong"}})
 with pytest.raises(DynamicError,match="followup_parent_identity_mismatch"):FollowupSegment(parent,tmp_path/"other",c,"sha")

def test_missing_original_budget_cannot_create_empty_continuation(tmp_path,monkeypatch):
 parent,c=setup_parent(tmp_path,monkeypatch)
 # A nonmatching path fails before touching an absent database.
 c["campaign_budget"]["path"]=str(parent/"absent.sqlite")
 with pytest.raises(DynamicError,match="followup_original_budget_mismatch"):FollowupSegment(parent,tmp_path/"segment",c,"sha")
 assert not (parent/"absent.sqlite").exists()

def test_rescore_action_never_constructs_team_transport(tmp_path,monkeypatch):
 from types import SimpleNamespace
 import trustfork.tools.plan_judge_followup as cli
 import trustfork.tools.first_dynamic_api as first
 calls=[]
 def forbidden(*a,**k):pytest.fail("Rescore must never construct a model/team transport")
 monkeypatch.setattr(first,"transport",forbidden)
 monkeypatch.setattr(cli,"accepted_judge",lambda *a:True)
 monkeypatch.setattr(cli,"clone_frozen_run",lambda source,dest:(calls.append(("clone",source)) or dest/"run.json"))
 monkeypatch.setattr(cli,"score_frozen",lambda segment,path,out:(calls.append(("judge",str(path))) or {"attempt":{"status":"completed"}}))
 runs=[{"protocol":p,"condition":c,"run_id":p+c,"path":str(tmp_path/(p+c)/"run.json")} for p in ("S","F") for c in ("HP","HA")]
 segment=SimpleNamespace(path=tmp_path/"segment",runs=runs)
 result=cli.rescore_gpt(segment)
 assert result["status"]=="completed" and result["new_team_model_requests"]==0
 assert len([x for x in calls if x[0]=="judge"])==4
