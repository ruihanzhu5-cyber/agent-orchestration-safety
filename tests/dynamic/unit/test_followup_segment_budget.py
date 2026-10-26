import pytest
from trustfork.runtime.dynamic.campaign_budget import CampaignBudget
from trustfork.runtime.dynamic.common import DynamicError

def test_segment_inherits_original_money_unknown_reservations_and_restart(tmp_path):
 p=tmp_path/"budget"
 old=CampaignBudget(p,campaign_id="original")
 old.reserve("old",phase="engineering_smoke",reserved_cost_cny=90,metadata={})
 old.submitted("old");old.settle("old",settled_cost_cny=89,usage={})
 b=CampaignBudget(p,campaign_id="original",must_exist=True,segment_id="followup",segment_cny=20,segment_identity={"parent":"original"})
 b.reserve("new",phase="engineering_smoke",reserved_cost_cny=10,metadata={})
 b.submitted("new");b.settle("new")
 assert b.summary()["remaining_cny"]==1 and b.segment_summary()["remaining_cny"]==10
 with pytest.raises(DynamicError,match="campaign_cost_exhausted"):b.reserve("too",phase="engineering_smoke",reserved_cost_cny=2,metadata={})
 assert CampaignBudget(p,campaign_id="original",must_exist=True,segment_id="followup",segment_cny=20,segment_identity={"parent":"original"}).segment_summary()["remaining_cny"]==10

def test_segment_twenty_atomic_reservations_and_identity_are_durable(tmp_path):
 p=tmp_path/"budget";CampaignBudget(p,campaign_id="original")
 b=CampaignBudget(p,campaign_id="original",must_exist=True,segment_id="followup",segment_cny=20,segment_identity={"parent":"original"})
 b.reserve("a",phase="interface_probe",reserved_cost_cny=11,metadata={})
 with pytest.raises(DynamicError,match="campaign_segment_cost_exhausted"):b.reserve("b",phase="engineering_smoke",reserved_cost_cny=10,metadata={})
 b.submitted("a");b.settle("a",settled_cost_cny=2,usage={})
 b.reserve("b",phase="engineering_smoke",reserved_cost_cny=18,metadata={})
 assert b.segment_summary()["remaining_cny"]==0
 with pytest.raises(DynamicError,match="campaign_segment_identity_mismatch"):CampaignBudget(p,campaign_id="original",must_exist=True,segment_id="followup",segment_cny=20,segment_identity={"parent":"wrong"})
 with pytest.raises(DynamicError,match="campaign_original_ledger_missing"):CampaignBudget(tmp_path/"absent",campaign_id="original",must_exist=True)
 assert not (tmp_path/"absent").exists()

def segment_worker(path,index,queue):
 try:
  b=CampaignBudget(path,campaign_id="original",must_exist=True,segment_id="followup",segment_cny=20,segment_identity={"parent":"original"})
  b.reserve("parallel"+str(index),phase="engineering_smoke",reserved_cost_cny=11,metadata={})
  queue.put("reserved")
 except DynamicError as e:queue.put(e.code)

def test_segment_concurrent_processes_cannot_reserve_over_twenty(tmp_path):
 import multiprocessing
 p=tmp_path/"budget";CampaignBudget(p,campaign_id="original")
 ctx=multiprocessing.get_context("spawn");q=ctx.Queue()
 processes=[ctx.Process(target=segment_worker,args=(p,i,q)) for i in range(2)]
 for process in processes:process.start()
 for process in processes:process.join(30);assert process.exitcode==0
 assert sorted(q.get(timeout=2) for _ in processes)==["campaign_segment_cost_exhausted","reserved"]
