import json,sqlite3,pytest
from trustfork.runtime.dynamic.campaign_budget import CampaignBudget
from trustfork.runtime.dynamic.small_api_budget import amend_original_segment,SEGMENT
from trustfork.runtime.dynamic.execution_attempt import migrate_attempts
from trustfork.tools.runtime_judge_review import attach_budget
from trustfork.runtime.dynamic.common import DynamicError

def prepared(tmp_path):
 p=tmp_path/'original.sqlite3';b=CampaignBudget(p,campaign_id='first-api-20261026',segment_id=SEGMENT,segment_cny=20,segment_identity={'identity_hash':'old'})
 b.reserve('old',phase='engineering_smoke',reserved_cost_cny=1,metadata={});b.submitted('old');b.settle('old',settled_cost_cny=.5,usage={})
 with sqlite3.connect(p) as db:
  db.row_factory=sqlite3.Row;baseline={'requests_before':[dict(v) for v in db.execute('SELECT * FROM requests ORDER BY request_id')],'segments_before':[dict(v) for v in db.execute('SELECT * FROM segments')]}
 return p,b,baseline

def test_no_unrecorded_increase_and_authorized_amendment_keeps_original_fees(tmp_path):
 p,b,baseline=prepared(tmp_path)
 with pytest.raises(DynamicError,match='campaign_segment_policy_invalid'):CampaignBudget(p,campaign_id='first-api-20261026',segment_id=SEGMENT,segment_cny=50.5,segment_identity={'identity_hash':'old'})
 result=amend_original_segment(p,baseline,backup=tmp_path/'backup.sqlite3')
 assert result['segment_ceiling_cny']==50.5 and result['max_judge_cny']==10 and result['all_existing_request_rows_unchanged']
 assert b.rows()[0]['settled']==500000 and b.summary()['remaining_cny']==99.5
 live=CampaignBudget(p,campaign_id='first-api-20261026',segment_id=SEGMENT,segment_cny=50.5,segment_identity={'identity_hash':'old'},must_exist=True)
 assert live.segment_summary()['remaining_cny']==50
 with pytest.raises(DynamicError,match='campaign_segment_cost_exhausted'):live.reserve('too-large',phase='engineering_smoke',reserved_cost_cny=51,metadata={})
 assert amend_original_segment(p,baseline,backup=tmp_path/'unused.sqlite3')['status']=='already_applied'
 assert not (tmp_path/'unused.sqlite3').exists()

def test_existing_attempt_association_and_attach_follow_authorized_bucket(tmp_path):
 p,b,baseline=prepared(tmp_path);amend_original_segment(p,baseline,backup=tmp_path/'backup.sqlite3')
 dry=migrate_attempts(p,apply=False);assert dry['segment_ceiling_micro_cny']==50500000
 from trustfork.tools import runtime_judge_review as module
 import shutil
 shutil.copy2(p,tmp_path/'campaign-budget.sqlite3')
 config=attach_budget({'campaign_budget':{}},tmp_path)
 assert config['campaign_budget']['segment_cny']==50.5


def test_second_authorization_is_judge_only_and_preserves_original_rows(tmp_path):
 from trustfork.runtime.dynamic.small_api_budget import amend_judge_followup,ROUND
 p,b,baseline=prepared(tmp_path);amend_original_segment(p,baseline,backup=tmp_path/'first-backup.sqlite3')
 original=b.rows();receipt=amend_judge_followup(p,backup=tmp_path/'judge-backup.sqlite3')
 assert receipt['new_segment_ceiling_cny']==60.5 and b.rows()==original
 assert amend_judge_followup(p,backup=tmp_path/'not-created.sqlite3')['status']=='already_applied'
 assert not (tmp_path/'not-created.sqlite3').exists()
 live=CampaignBudget(p,campaign_id='first-api-20261026',segment_id=SEGMENT,segment_cny=60.5,segment_identity={'identity_hash':'old'},must_exist=True)
 # Consume the previous ceiling with unchanged old-round activity.
 live.reserve('existing-round',phase='engineering_smoke',reserved_cost_cny=50,metadata={'kind':'model'});live.submitted('existing-round');live.settle('existing-round',settled_cost_cny=50,usage={})
 with pytest.raises(DynamicError,match='campaign_segment_cost_exhausted'):live.reserve('extra-team',phase='engineering_smoke',reserved_cost_cny=1,metadata={'kind':'model'})
 metadata={'kind':'judge','small_api_judge_group_id':ROUND,'execution_attempt_id':'small-api-th-tul-frozen-20261027-a6','execution_stage_id':'trajectory/new-S-HP'}
 live.reserve('authorized-judge',phase='engineering_smoke',reserved_cost_cny=1,metadata=metadata)
 assert live.summary()['remaining_cny']==48.5
 with pytest.raises(DynamicError,match='small_api_judge_cost_exhausted'):live.reserve('judge-too-large',phase='engineering_smoke',reserved_cost_cny=10,metadata=metadata)
