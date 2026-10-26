import json
from trustfork.runtime.dynamic.common import write_json
from trustfork.runtime.dynamic.campaign_budget import CampaignBudget
from trustfork.runtime.dynamic.review_export import export_campaign
def test_followup_exports_explicit_sources_pass_states_and_only_segment_costs(tmp_path):
 source=tmp_path/"source";source.mkdir()
 write_json(source/"campaign.json",{"campaign_id":"followup","parent_campaign_id":"old","identity":{"commit":"new"},"status":"blocked"})
 write_json(source/"segment.json",{"parent_campaign_id":"old","execution_code_sha":"new","source_hash":"old-hash"})
 write_json(source/"resolved-config.json",{"judge_binding":"deepseekflash","key_env":"private-credential-variable"})
 write_json(source/"input-size-audit.json",{"service_prompt_tokens":None,"token_estimate":123,"bytes":999})
 write_json(source/"fixtures/summary.json",{"passed":False})
 write_json(source/"actions/rescore_old_gpt.json",{"status":"blocked"})
 write_json(source/"gpt-rescore/F-HP/judge-followup/pass-states.json",{"response":{"status":"not_applicable"},"trajectory":{"status":"blocked"}})
 db=tmp_path/"original.sqlite";b=CampaignBudget(db,campaign_id="original")
 b.reserve("old",phase="interface_probe",reserved_cost_cny=1,metadata={});b.submitted("old");b.settle("old",settled_cost_cny=.5,usage={})
 seg=CampaignBudget(db,campaign_id="original",must_exist=True,segment_id="s",segment_cny=20,segment_identity={"old":"hash"})
 seg.reserve("new",phase="interface_probe",reserved_cost_cny=1,metadata={});seg.submitted("new");seg.settle("new",settled_cost_cny=.1,usage={})
 dest=tmp_path/"public";manifest=export_campaign(source,dest,ledger_path=db,ledger_segment_id="s")
 assert "new" in (dest/"costs.csv").read_text() and "\\nold," not in (dest/"costs.csv").read_text()
 assert (dest/"input-size-audit.json").exists() and (dest/"segment.json").exists()
 assert (dest/"evidence/gpt-rescore/F-HP/judge-followup/pass-states.json").exists()
 text=(dest/"README.md").read_text()
 assert "Parent campaign: old" in text and "Plan_Judge_Followup_Report" in text and "Runtime_Budget_And_First" not in text
 assert "private-credential-variable" not in (dest/"config.redacted.json").read_text()
 assert any(x["reason"]=="outside_explicit_text_whitelist_original_retained_locally" for x in manifest["missing_or_excluded"]) is False
