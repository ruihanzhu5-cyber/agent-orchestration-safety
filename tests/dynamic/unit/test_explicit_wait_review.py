import time
import pytest
from trustfork.runtime.dynamic.events import EventLedger
from trustfork.runtime.dynamic.membership import Membership
from trustfork.runtime.dynamic.lifecycle import Lifecycle
from trustfork.runtime.dynamic.scheduler import Scheduler
from trustfork.runtime.dynamic.delegations import Delegations
from trustfork.runtime.dynamic.common import DynamicError

def state(tmp_path):
 l=EventLedger(tmp_path/"events.jsonl","b","p001")
 m=Membership(l);life=Lifecycle(l,"s");life.state="RUNNING";s=Scheduler("b",l,m,life)
 return l,m,life,s

def test_wait_releases_permit_deduplicates_wake_and_closes_race(tmp_path):
 l,m,life,s=state(tmp_path)
 s.enqueue_batch(["Main","A","B"],reason="test")
 assert s.permit(actors=["Main"])
 v=s.observable_version("Main")
 # Arrival after the tool's check, before the actor's completion cannot be lost.
 s.notify(["Main"],"message")
 assert s.complete("Main",outcome={"state":"waiting","after_version":v,"timeout_seconds":10,"pending_work":True})=="changed"
 assert len([r for r in s.queue if r["actor_id"]=="Main"])==1
 assert s.permit(actors=["Main"])
 v=s.observable_version("Main")
 assert s.complete("Main",outcome={"state":"waiting","after_version":v,"timeout_seconds":10,"pending_work":True})=="waiting"
 assert "Main" not in s.active and "Main" in s.waiting
 for actor in ["A","B"]:
  assert s.permit(actors=[actor])
  s.complete(actor,unfinished=True)
 assert s.permit(actors=["A"])
 s.notify(["Main"],"formal_delivery");s.notify(["Main"],"peer_message")
 assert "Main" not in s.waiting
 assert len([r for r in s.queue if r["actor_id"]=="Main"])==1
 assert not any(e["event_type"]=="message_exposed" for e in l.rows)

@pytest.mark.parametrize("reason",["timeout","cancelled","stage_deadline","resource_ended","member_released"])
def test_wait_terminal_and_timeout(tmp_path,reason):
 l,m,life,s=state(tmp_path);s.enqueue_batch(["Main"],reason="test");s.permit()
 s.complete("Main",outcome={"state":"waiting","after_version":0,"timeout_seconds":0.01,"pending_work":True})
 if reason=="timeout":s.poll_waiters(now=time.time()+1)
 else:s.cancel_waits(reason)
 assert not s.waiting
 assert s.wake_results["Main"]["reason"]==reason


def test_no_pending_work_and_bad_version(tmp_path):
 l,m,life,s=state(tmp_path);s.enqueue_batch(["Main"],reason="test");s.permit()
 assert s.complete("Main",outcome={"state":"waiting","after_version":0,"timeout_seconds":1,"pending_work":False})=="no_pending_work"
 assert not s.waiting
 with pytest.raises(DynamicError):s.wait_intent("Main",after_version=True,timeout_seconds=1,pending_work=True)


def test_public_work_status_does_not_leak_task_or_goals(tmp_path):
 l,m,life,s=state(tmp_path);d=Delegations(l,m)
 row=d.prepare("A","private task wording",stage_id="s")
 result=d.work_status("Main",epoch=0)
 assert result[0]["delegation_id"]==row["delegation_id"]
 assert "task_text" not in result[0] and "invocation_id" in result[0]
 assert d.work_status("B",epoch=0)==[]


def test_wait_snapshot_roundtrip(tmp_path):
 l,m,life,s=state(tmp_path);s.enqueue_batch(["Main"],reason="test");s.permit()
 s.complete("Main",outcome={"state":"waiting","after_version":0,"timeout_seconds":20,"pending_work":True})
 snapshot=s.coordination_snapshot()
 other=Scheduler("b",l,m,life);other.restore_coordination(snapshot)
 assert other.waiting==s.waiting and other.versions==s.versions
 other.notify(["Main"],"message")
 assert not other.waiting and len(other.queue)==1

@pytest.mark.parametrize('tail,expected',[(None,'waiting'),('write','continue'),('get_team_directory','continue')])
def test_last_successful_tool_controls_wait_precedence(tail,expected):
 from trustfork.runtime.dynamic.turn_outcome import turn_outcome
 events=[{'type':'tool_execution_end','toolName':'wait_for_update','isError':False}]
 if tail:events.append({'type':'tool_execution_end','toolName':tail,'isError':False})
 assert turn_outcome({'response':{'stopReason':'toolUse'},'events':events},{'state':'waiting'})['state']==expected
 assert turn_outcome({'response':{'stopReason':'length'},'events':events},{'state':'waiting'})['reason']=='output_limit'

@pytest.mark.parametrize('which,reason',[("requests","request_limit"),("tokens","token_limit"),("time","time_limit")])
def test_budget_end_reasons(which,reason):
 from trustfork.runtime.dynamic.budget import Budget
 b=Budget(request_limit=1,token_limit=8,per_request=4)
 if which=='requests':b.reserve('r',0)
 elif which=='tokens':b.output_tokens=6
 else:b.deadline=0
 assert b.termination_reason()==reason
