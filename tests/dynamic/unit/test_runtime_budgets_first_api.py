import concurrent.futures
import time
import pytest
from trustfork.runtime.dynamic.budget import Budget
from trustfork.runtime.dynamic.common import DynamicError
from trustfork.runtime.dynamic.experiment_config import resolve_runtime_budget
from trustfork.agents.pi_dynamic import PiDynamic
from trustfork.runtime.dynamic.events import EventLedger
from trustfork.runtime.dynamic.membership import Membership
from trustfork.runtime.dynamic.delegations import Delegations
from trustfork.runtime.dynamic.lifecycle import Lifecycle
from trustfork.runtime.dynamic.mailbox import Mailbox
from trustfork.runtime.dynamic.scheduler import Scheduler

def test_full_generation_budget_waits_for_inflight_and_never_shrinks():
 b=Budget(token_limit=20,per_request=10)
 a=b.reserve('a',0);c=b.reserve('c',0)
 assert not b.available() and not b.exhausted()
 with pytest.raises(DynamicError,match='budget_waiting_for_inflight'):b.reserve('d',0)
 b.finish(a['attempt_id'],output_tokens=1,status='success')
 assert not b.available() and not b.exhausted()
 b.finish(c['attempt_id'],output_tokens=1,status='success')
 assert b.available() and b.reserve('d',0)['max_output_tokens']==10

def test_settled_remainder_ends_without_tiny_generation():
 b=Budget(token_limit=15,per_request=10)
 a=b.reserve('a',0);b.finish(a['attempt_id'],output_tokens=6,status='success')
 assert b.exhausted() and not b.available()
 with pytest.raises(DynamicError,match='budget_exhausted'):b.reserve('b',0)
 assert len(b.attempts)==1

def test_budget_restore_preserves_spend_and_wall_clock(monkeypatch):
 b=Budget(token_limit=30,per_request=10)
 a=b.reserve('a',0);b.finish(a['attempt_id'],output_tokens=4,status='success')
 snapshot=b.snapshot();now=time.time()
 monkeypatch.setattr(time,'time',lambda:now+3)
 restored=Budget.restore(snapshot)
 assert restored.output_tokens==4 and restored.attempts==b.attempts
 assert restored.snapshot()['remaining_seconds']<snapshot['remaining_seconds']-2

def test_resolved_model_budgets_and_override_identity(tmp_path):
 g=PiDynamic('p001',tmp_path/'g',team_model='gpt4o')
 d=PiDynamic('p001',tmp_path/'d',team_model='deepseekflash')
 assert g.runtime_budget['per_request']==8192 and d.runtime_budget['per_request']==16384
 assert d.runtime_budget['token_limit']==192000
 assert g.experiment.export()['runtime_budget']==g.runtime_budget
 with pytest.raises(DynamicError,match='invalid_runtime_budget'):
  resolve_runtime_budget('gpt4o',{'per_request':1})

def runtime(tmp_path):
 r=PiDynamic.__new__(PiDynamic)
 r.case={'case_id':'p001'};r.ledger=EventLedger(tmp_path/'events.jsonl','b','p001')
 r.lifecycle=Lifecycle(r.ledger);r.lifecycle.state='RUNNING'
 r.membership=Membership(r.ledger);r.delegations=Delegations(r.ledger,r.membership)
 r.mailbox=Mailbox(r.ledger,r.membership);r.scheduler=Scheduler('block',r.ledger,r.membership,r.lifecycle)
 r.formal_deliverables={};r.main_revision=0;r.confirming_final=False;r.pending_final=None
 r.termination_reason=None
 return r

def test_partial_sub_delivery_is_terminal_and_not_implicitly_rescheduled(tmp_path):
 r=runtime(tmp_path)
 invocation=r.delegations.prepare('A','task',source='initial_plan')
 r.delegations.release(epoch=0);invocation=r.delegations.start(invocation['delegation_id'],stage_id='initial',epoch=0)
 r.scheduler.enqueue_batch(['A'],reason='task');r.scheduler.permit()
 response={'stopReason':'length','content':[{'type':'text','text':'partial observed risk'}]}
 r._formal('A',invocation,response,'request')
 future=concurrent.futures.Future();future.set_result({'response':response,'input_revision':0})
 r._settle(future,{future:('A',invocation)})
 assert invocation['status']=='terminal' and invocation['terminal_status']=='resource_ended'
 assert r._next_invocation('A') is None
 assert 'A' not in r.scheduler.continuations and all(x['actor_id']!='A' for x in r.scheduler.queue)
 value=next(iter(r.formal_deliverables.values()))
 assert value['result_status']=='partial' and value['completion_status']=='partial'
 assert r.mailbox.messages[0]['content']=='partial observed risk'
 from trustfork.scoring.dynamic_adapter import extract_formal_deliverables
 assert extract_formal_deliverables(r.ledger.rows,task_id='p001')[0]['completion_status']=='partial'

def test_main_length_never_becomes_normal_final(tmp_path):
 r=runtime(tmp_path);r.scheduler.enqueue_batch(['Main'],reason='task');r.scheduler.permit()
 response={'stopReason':'length','content':[{'type':'text','text':'incomplete final'}]}
 future=concurrent.futures.Future();future.set_result({'response':response,'input_revision':0})
 r._settle(future,{future:('Main',None)})
 assert r.pending_final['text'] is None and r.termination_reason=='output_limit'
 assert 'Main' not in r.scheduler.continuations
