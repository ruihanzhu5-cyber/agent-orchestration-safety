import pytest,concurrent.futures
from trustfork.runtime.dynamic.campaign_budget import CampaignBudget
from trustfork.runtime.dynamic.common import DynamicError
G='small-api-collection-20261027'
def meta(attempt='a'):return {'small_api_judge_group_id':G,'execution_attempt_id':attempt,'kind':'judge'}
def test_unknown_reservation_holds_two_cny_across_new_attempts(tmp_path):
 b=CampaignBudget(tmp_path/'b.sqlite3',campaign_id='first-api-20261026')
 b.reserve('a',phase='interface_probe',reserved_cost_cny=1.5,metadata=meta());b.submitted('a');b.settle('a')
 with pytest.raises(DynamicError,match='small_api_judge_cost_exhausted'):b.reserve('new',phase='interface_probe',reserved_cost_cny=.51,metadata=meta('changed-code'))
 b.reserve('within',phase='interface_probe',reserved_cost_cny=.5,metadata=meta('changed-code'))
 assert b.summary()['unsettled_reserved_cny']==2

def test_forty_eight_limit_includes_every_repair_and_calibration_and_cannot_reset(tmp_path):
 b=CampaignBudget(tmp_path/'b.sqlite3',campaign_id='first-api-20261026')
 for i in range(48):
  name=str(i);b.reserve(name,phase='interface_probe',reserved_cost_cny=.001,metadata=meta(str(i)));b.submitted(name);b.settle(name,settled_cost_cny=.001,usage={})
 with pytest.raises(DynamicError,match='small_api_judge_request_limit'):b.reserve('49',phase='interface_probe',reserved_cost_cny=.001,metadata=meta('new-attempt'))
 assert b.summary()['submitted_attempts']==48

def test_concurrent_reservations_cannot_exceed_group_ceiling(tmp_path):
 b=CampaignBudget(tmp_path/'b.sqlite3',campaign_id='first-api-20261026')
 def reserve(i):
  try:b.reserve(str(i),phase='interface_probe',reserved_cost_cny=1,metadata=meta(str(i)));return True
  except DynamicError as e:assert e.code=='small_api_judge_cost_exhausted';return False
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:assert sum(pool.map(reserve,range(4)))==2
 assert b.summary()['unsettled_reserved_cny']==2

def test_authorized_ten_cny_applies_across_attempts_and_tamper_is_rejected(tmp_path):
 import sqlite3
 from test_small_budget_amendment import prepared
 from trustfork.runtime.dynamic.small_api_budget import amend_original_segment,SEGMENT
 p,b,baseline=prepared(tmp_path);amend_original_segment(p,baseline,backup=tmp_path/'backup.sqlite3')
 b=CampaignBudget(p,campaign_id='first-api-20261026',segment_id=SEGMENT,segment_cny=50.5,segment_identity={'identity_hash':'old'})
 b.reserve('first',phase='engineering_smoke',reserved_cost_cny=9,metadata=meta());b.submitted('first');b.settle('first',settled_cost_cny=9,usage={})
 b.reserve('last',phase='engineering_smoke',reserved_cost_cny=1,metadata=meta('changed-code'))
 with pytest.raises(DynamicError,match='small_api_judge_cost_exhausted'):b.reserve('over',phase='engineering_smoke',reserved_cost_cny=.000001,metadata=meta())
 with sqlite3.connect(p) as db:db.execute('UPDATE small_api_budget_amendments SET max_judge=11000000')
 with pytest.raises(DynamicError,match='small_api_judge_policy_invalid'):b.reserve('tampered',phase='engineering_smoke',reserved_cost_cny=.000001,metadata=meta())

def test_transport_retains_group_in_actual_reservation_metadata(tmp_path):
 import json
 from test_campaign_budget import configured_campaign
 from trustfork.runtime.dynamic.provider import ProviderTransport
 c=configured_campaign(tmp_path/'budget.sqlite3')
 def http(*args):return {'status':200,'headers':{'content-type':'application/json'},'body':json.dumps({'usage':{'prompt_tokens':10,'completion_tokens':5}})}
 t=ProviderTransport(c,mode='mock',journal=tmp_path/'requests.jsonl',http=http,kind='judge',max_requests=2)
 t.execution_context=meta()
 t.request('gpt4o',{'url':'https://mock.invalid/v1/chat/completions','method':'POST','body':json.dumps({'model':'exact-fixture','messages':[],'max_tokens':100})},request_id='group-metadata')
 rows=CampaignBudget(tmp_path/'budget.sqlite3',campaign_id='first-api-20261026').rows()
 assert len(rows)==1 and rows[0]['metadata']['small_api_judge_group_id']==G
