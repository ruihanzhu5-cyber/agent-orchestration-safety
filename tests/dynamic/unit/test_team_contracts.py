import copy
from collections import Counter
import pytest
from trustfork.runtime.dynamic.common import DynamicError, repo_root, read_json, canonical
from trustfork.runtime.dynamic.events import EventLedger
from trustfork.runtime.dynamic.profile_service import build_profile, ProfileService, FAMILIES, assigned_corpus
from trustfork.runtime.dynamic.goals import bind_goals, focal_actor, LAYOUTS, NORMAL_GOAL
from trustfork.runtime.dynamic.case_loader import load_case
from trustfork.runtime.dynamic.mailbox import Mailbox
from trustfork.runtime.dynamic.membership import Membership
from trustfork.runtime.dynamic.delegations import Delegations
from trustfork.runtime.dynamic.initial_plan import parse_initial_plan
from trustfork.runtime.dynamic.lifecycle import Lifecycle
from trustfork.runtime.dynamic.scheduler import Scheduler
from trustfork.runtime.dynamic.budget import Budget


def test_exact_frozen_r1_example_and_all_queries():
    fixture = read_json(repo_root() / 'tests/dynamic/fixtures/portfolio_profiles_r1_c.v1.json')
    for condition in ('HP', 'HA', 'MP', 'MA'):
        bundle = build_profile('C', 'H' if condition[0] == 'H' else 'M')
        assert bundle['profile'] == fixture['profiles_by_condition'][condition]['target_profile']
        assert bundle['samples'] == fixture['artifact_registry_by_condition'][condition]
        assert bundle['historical_configs'] == fixture['historical_config_registry']
        service = ProfileService('b', {'C':bundle})
        assert 'records' not in service.get_public_profile('C', 'summary')['external_record']
        assert 'recent_summary' not in service.get_public_profile('C', 'records')['external_record']
        assert len(service.get_public_profile('C', 'full')['external_record']['records']) == 20
        assert service.get_profile_record('profile://C/records/01')['record_id'] == 'record_01'
        assert service.get_work_sample('profile://C/work-samples/01')['assessment']['measure'] == 'sample_consistency'
        assert service.get_profile_statistics('C', 'recent')['evaluated_tasks'] == 5
        assert service.get_historical_config('history_config_C_v1')['model_binding_ref'] == 'C'


@pytest.mark.parametrize('actor', ['C','D'])
@pytest.mark.parametrize('level,passed', [('H',18),('M',14),('80',16),('60',12),('none',0)])
def test_portfolio_permutations_counts_and_ownership(actor, level, passed):
    failures = Counter()
    for corpus in ('R1','R2','R3','R4'):
        bundle = build_profile(actor, level, corpus=corpus)
        profile = bundle['profile']['external_record']
        assert profile['passed_tasks'] == passed
        assert profile['completion_rate_pct'] == (None if level == 'none' else passed * 5)
        assert Counter(r['task_family'] for r in profile['records']) == (Counter() if level=='none' else Counter({f:5 for f in FAMILIES}))
        for row in profile['records']:
            assert row['subject_agent_id'] == actor and f'://{actor}/' in row['evidence_ref']
            assert row['historical_config_id'] == f'history_config_{actor}_v1'
            sample = bundle['samples'][row['work_sample_ref']]
            assert sample['assessment']['recorded_result'] == row['result']
            assert len(sample['submission']['content']) == sample['assessment']['covered_item_count']
            if row['result'] == 'fail': failures[row['task_family']] += 1
        service = ProfileService('b', {actor:bundle})
        with pytest.raises(DynamicError, match='cross_branch_profile_reference'):
            service.resolve(f'profile://{actor}/records/01', branch_id='other')
    assert len(set(failures.values())) <= 1


def test_high_medium_only_result_related_fields_differ():
    for corpus in ('R1','R2','R3','R4'):
        high, middle = (build_profile('D', x, corpus=corpus) for x in ('H','M'))
        for a,b in zip(high['profile']['external_record']['records'],middle['profile']['external_record']['records']):
            a,b=copy.deepcopy(a),copy.deepcopy(b)
            for row in (a,b):
                row.pop('result');row.pop('outcome_detail');row['assessment'].pop('feedback')
            assert a==b
        assert high['historical_configs']==middle['historical_configs']
        for ref in high['samples']:
            a,b=copy.deepcopy(high['samples'][ref]),copy.deepcopy(middle['samples'][ref])
            for row in (a,b):
                row['submission'].pop('content');row['assessment'].pop('covered_item_count');row['assessment'].pop('recorded_result')
            assert a==b


def test_focal_goals_and_different_original_history_tasks():
    catalog = read_json(repo_root() / 'trustfork/config/dynamic/cases.json')
    for layout, expected in [('P1',('5039','30058')),('P2',('5039','30058')),('P3',('10025','25011')),('P4',('10025','25011'))]:
        actual = [catalog[x]['source_scenario_card_id'] for x in LAYOUTS[layout]['history']]
        assert all(e in a for e,a in zip(expected,actual))
        for case_id in ('p001','p024'):
            case=load_case(case_id)
            normal=bind_goals(case,layout,'HP'); risk=bind_goals(case,layout,'HA')
            q=normal['q']
            assert sum(v != NORMAL_GOAL for v in risk['goals'].values())==1
            assert risk['goals'][q] != normal['goals'][q]
            assert normal['goals'][normal['r']]==risk['goals'][risk['r']]==NORMAL_GOAL
    assert focal_actor('p001','P1')=='C' and focal_actor('p001','P3')=='D'
    assert focal_actor('p024','P1')=='D' and focal_actor('p024','P3')=='C'


def team(tmp_path):
    ledger=EventLedger(tmp_path/'events','b','p001'); membership=Membership(ledger)
    return ledger,membership,Mailbox(ledger,membership)


def test_mailbox_actual_exposure_late_arrival_and_maintenance(tmp_path):
    ledger,membership,box=team(tmp_path)
    membership.admit_atomic(['C','D'])
    first=box.enqueue('C',['A'],'first',branch_id='b',message_id='one')
    box.enqueue('D',['B'],'private peer',branch_id='b')
    assert box.claim('Main','main',epoch=0)==[]
    assert box.claim('A','maint',epoch=0,maintenance=True)==[]
    packet=box.claim('A','a1',epoch=0)
    box.advance('A','a1','input_frozen')
    box.enqueue('C',['A'],'late',branch_id='b',message_id='two')
    box.advance('A','a1','submitted')
    assert box.confirm('A','a1',{'peer_messages':packet},successful=True)==['one']
    packet2=box.claim('A','a2',epoch=0)
    assert [x['message_id'] for x in packet2]==['two']
    box.advance('A','a2','input_frozen');box.advance('A','a2','submitted')
    assert box.confirm('A','a2',{'peer_messages':packet2},successful=False)==[]
    assert [x['message_id'] for x in box.claim('A','a3',epoch=0)]==['two']
    assert len([x for x in ledger.rows if x['event_type']=='message_exposed'])==1
    with pytest.raises(DynamicError,match='cross_branch_message'):
        box.enqueue('C',['A'],'no',branch_id='other')
    membership.release('D')
    with pytest.raises(DynamicError,match='message_member_unavailable'):
        box.enqueue('C',['D'],'no',branch_id='b')


def test_pending_messages_migrate_once_or_cancel(tmp_path):
    _,membership,box=team(tmp_path)
    box.enqueue('A',['B'],'carry',branch_id='b')
    box.stage_transition(0,1,new_session=False)
    box.stage_transition(0,1,new_session=False)
    assert len(box.messages)==1 and box.messages[0]['carried_from_epoch']==0
    box.stage_transition(1,2,new_session=True)
    assert box.claim('B','next',epoch=2)==[]
    assert box.messages[0]['delivery']['B']['status']=='cancelled_new_session'


def test_scheduler_zero_sub_before_release_fifo_and_four_requests(tmp_path):
    ledger,membership,_=team(tmp_path)
    life=Lifecycle(ledger);scheduler=Scheduler('block',ledger,membership,life)
    scheduler.enqueue_batch(['A','B'],reason='initial_pending')
    assert scheduler.permit() is None
    life.transition('PLAN_READY');membership.admit_atomic(['C','D'])
    life.transition('JOINING');life.transition('COORDINATING')
    scheduler.begin_startup(['C','D']);scheduler.enqueue_batch(['C','D'],reason='startup')
    assert scheduler.permit() is None
    life.transition('RUNNING')
    permits=[scheduler.permit() for _ in range(4)]
    assert {x['actor_id'] for x in permits}==set('ABCD') and scheduler.permit() is None
    assert [x['ready_seq'] for x in permits]==sorted(x['ready_seq'] for x in permits)
    for actor in 'ABCD': scheduler.complete(actor,unfinished=actor in 'CD')
    for _ in range(3):
        for _ in range(2):
            permit=scheduler.permit(); scheduler.complete(permit['actor_id'],unfinished=True)
    assert scheduler.final_allowed()
    assert {x['status'] for x in scheduler.startup.values()}=={'four_request_limit'}
    assert {x['requests'] for x in scheduler.startup.values()}=={4}
    assert len(scheduler.queue)==2  # unfinished work may continue after the slice


def test_plan_no_fake_work_and_budget_reservations(tmp_path):
    text='{"plan_status":"refusal","assignments":[],"draft_answer":"I cannot complete this."}'
    assert parse_initial_plan(text)['plan']['assignments']==[]
    with pytest.raises(DynamicError):
        parse_initial_plan('{"plan_status":"delegate","assignments":[{"recipient":"C","task_text":"x"}],"draft_answer":null}')
    budget=Budget(request_limit=3,token_limit=10,per_request=6)
    first=budget.reserve('r',0)
    assert first['max_output_tokens']==6 and not budget.available() and not budget.exhausted()
    with pytest.raises(DynamicError,match='budget_waiting_for_inflight'):budget.reserve('s',0)
    budget.finish(first['attempt_id'],output_tokens=2,status='success')
    assert budget.available()
    second=budget.reserve('s',0)
    assert second['max_output_tokens']==6
    restored=Budget.restore(budget.snapshot())
    assert restored.output_tokens==2 and len(restored.attempts)==2
    restored.finish(second['attempt_id'],output_tokens=0,status='success')
    with pytest.raises(DynamicError,match='transport_retry_limit'):
        restored.reserve('r',3)


def audit_runtime(tmp_path, protocol='S'):
    """Use the real coordination/queue methods without a model or container."""
    from trustfork.agents.pi_dynamic import PiDynamic
    runtime=PiDynamic.__new__(PiDynamic)
    runtime.protocol=protocol;runtime.case=load_case('p001')
    runtime.ledger=EventLedger(tmp_path/'audit-events','audit-branch','p001')
    runtime.membership=Membership(runtime.ledger)
    runtime.delegations=Delegations(runtime.ledger,runtime.membership)
    runtime.mailbox=Mailbox(runtime.ledger,runtime.membership)
    runtime.lifecycle=Lifecycle(runtime.ledger,'ask');runtime.lifecycle.state='RUNNING'
    runtime.scheduler=Scheduler('audit',runtime.ledger,runtime.membership,runtime.lifecycle)
    runtime.delegations.startup_protected=runtime.scheduler.protects_delegation
    runtime.main_revision=0;runtime.formal_deliverables={};runtime.created=[]
    runtime._create_actor=lambda actor:runtime.created.append(actor)
    return runtime


def audit_scope(runtime):
    return {'stage_epoch':runtime.lifecycle.epoch,'stage_id':runtime.lifecycle.stage_id,
            'request_id':'actual-main-request','invocation_id':None}


@pytest.mark.parametrize('protocol',['S','L'])
def test_audit_open_startup_cannot_be_released_updated_or_cancelled(tmp_path,protocol):
    runtime=audit_runtime(tmp_path,protocol)
    runtime.membership.admit_atomic(['C','D']);runtime.scheduler.begin_startup(['C','D'])
    row=runtime.delegations.prepare('C','Original task',source='runtime_startup',stage_id=runtime.lifecycle.stage_id)
    runtime.scheduler.bind_startup(row)
    for name,args in [('release_member',{'actor_id':'C'}),
            ('update_delegation',{'delegation_id':row['delegation_id'],'task_text':'skip startup'}),
            ('cancel_delegation',{'delegation_id':row['delegation_id']})]:
        result=runtime._coordinate('Main',name,args,audit_scope(runtime))
        assert result['status']=='startup_contract_active'
    assert runtime.membership.admitted('C')
    assert runtime.scheduler.startup['C']['requests']==0 and runtime.scheduler.startup['C']['status']=='open'
    assert runtime.delegations.get(row['delegation_id'])['task_text']=='Original task'
    assert not runtime.scheduler.final_allowed()


def test_audit_f_recruit_only_registers_and_does_not_start_work(tmp_path):
    runtime=audit_runtime(tmp_path,'F')
    runtime._coordinate('Main','recruit',{'actor_ids':['C']},audit_scope(runtime))
    assert runtime.created==['C'] and runtime.membership.admitted('C')
    assert runtime.delegations.rows==[] and list(runtime.scheduler.queue)==[]
    assert runtime.scheduler.startup['C']['status']=='not_admitted'
    assert runtime.scheduler.final_allowed()
    runtime._coordinate('Main','delegate_work',{'actor_id':'C','task_text':'voluntary work'},audit_scope(runtime))
    assert runtime.scheduler.permit()['actor_id']=='C'
    assert runtime._next_invocation('C')['source']=='main_voluntary'


def test_audit_f_peer_message_is_a_real_wake_source(tmp_path):
    runtime=audit_runtime(tmp_path,'F')
    runtime._coordinate('Main','recruit',{'actor_ids':['C']},audit_scope(runtime))
    runtime._coordinate('A','send_message',{'recipients':['C'],'content':'Please inspect the shared task'},audit_scope(runtime))
    assert runtime.delegations.rows==[]
    assert runtime.scheduler.permit()['actor_id']=='C'
    assert runtime._next_invocation('C') is None


def test_audit_delegation_versions_and_scope_are_append_only(tmp_path):
    runtime=audit_runtime(tmp_path)
    row=runtime.delegations.prepare('A','first',epoch=2,stage_id='fragment_3',request_id='prepare')
    runtime.delegations.update(row['delegation_id'],'second',stage_id='fragment_3',epoch=2,request_id='update')
    runtime.delegations.cancel(row['delegation_id'],stage_id='fragment_3',epoch=2,request_id='cancel')
    events=[e for e in runtime.ledger.rows if e['event_type'].startswith('delegation_')]
    assert [e['event_type'] for e in events]==['delegation_prepared','delegation_updated','delegation_cancelled']
    assert [e['payload']['version'] for e in events]==[1,2,3]
    assert events[0]['payload']['task_text']=='first'
    assert events[1]['payload']['previous_task_text']=='first'
    assert events[1]['payload']['task_text']=='second'
    assert [e['request_id'] for e in events]==['prepare','update','cancel']
    assert all(e['stage_id']=='fragment_3' and e['stage_epoch']==2 for e in events)


def test_audit_cancelled_queue_marker_does_not_drop_peer_or_start_empty_turn(tmp_path):
    runtime=audit_runtime(tmp_path)
    runtime.scheduler.work_available=runtime._has_pending_work
    row=runtime.delegations.prepare('A','cancelled task');runtime._release()
    runtime.delegations.cancel(row['delegation_id'])
    assert runtime.scheduler.permit() is None
    runtime.mailbox.enqueue('B',['A'],'peer task remains',branch_id='audit-branch')
    runtime.scheduler.enqueue_batch(['A'],reason='peer_message')
    assert runtime.scheduler.permit()['actor_id']=='A'
    runtime.scheduler.complete('A',unfinished=True)
    packet=runtime.mailbox.claim('A','read-peer',epoch=0)
    runtime.mailbox.advance('A','read-peer','input_frozen');runtime.mailbox.advance('A','read-peer','submitted')
    runtime.mailbox.confirm('A','read-peer',{'peer_messages':packet},successful=True)
    assert runtime.scheduler.permit()['actor_id']=='A'  # real unfinished batch continuation
    runtime.scheduler.complete('A',unfinished=False)
    runtime.scheduler.enqueue_batch(['A'],reason='stale_after_cancel')
    assert runtime.scheduler.permit() is None


def test_audit_message_recipient_terminal_replay_and_coverage(tmp_path):
    from trustfork.scoring.dynamic_metrics import automatic_metrics
    runtime=audit_runtime(tmp_path);runtime.membership.admit_atomic(['C','D'])
    runtime.mailbox.enqueue('C',['A','Main'],'same result',branch_id='audit-branch')
    packet=runtime.mailbox.claim('A','a',epoch=0);runtime.mailbox.advance('A','a','input_frozen');runtime.mailbox.advance('A','a','submitted')
    runtime.mailbox.confirm('A','a',{'peer_messages':packet},successful=True)
    runtime.mailbox.stage_transition(0,1,new_session=True)
    values,_=automatic_metrics({'q':'C','case_id':'p001'},runtime.ledger.rows,[])
    assert values['delivery_coverage']['fraction']==1
    assert values['delivery_coverage_recipient']['fraction']==0.5
    assert values['message_recipient_terminal_counts']=={'confirmed_exposure':1,'cancelled_new_session':1}


def test_audit_formal_delivery_has_stable_message_and_source_links(tmp_path):
    runtime=audit_runtime(tmp_path)
    row=runtime.delegations.prepare('A','work',source='initial_plan')
    runtime._formal('A',runtime.delegations.get(row['delegation_id']),
        {'content':[{'type':'text','text':'actual work result'}],'stopReason':'stop'},'a-request')
    event=next(e for e in runtime.ledger.rows if e['event_type']=='formal_deliverable')
    message=next(e for e in runtime.ledger.rows if e['event_type']=='message_enqueued')
    assert event['payload']['message_id']==message['message_id']
    assert message['payload']['deliverable_id']==event['payload']['deliverable_id']
    assert message['payload']['source_event_ref']=='audit-branch::'+event['event_id']
    assert any(e['event_type']=='delegation_completed' for e in runtime.ledger.rows)


def test_audit_startup_budget_termination_emits_actual_counts_and_allows_release(tmp_path):
    runtime=audit_runtime(tmp_path);runtime.membership.admit_atomic(['C','D'])
    runtime.scheduler.begin_startup(['C','D']);runtime.scheduler.terminate_startup('global_budget_or_timeout')
    closed=[e for e in runtime.ledger.rows if e['event_type']=='startup_slice_closed']
    assert len(closed)==2 and all(e['payload']['actual_requests']==0 for e in closed)
    assert all(e['payload']['terminal_status']=='global_budget_or_timeout' for e in closed)
    assert runtime._coordinate('Main','release_member',{'actor_id':'C'},audit_scope(runtime))['status']=='released'
    release=next(e for e in runtime.ledger.rows if e['event_type']=='member_released')
    assert release['stage_id']=='ask' and release['request_id']=='actual-main-request'


def test_audit_explicit_initial_invocation_completion_closes_startup(tmp_path):
    from concurrent.futures import Future
    runtime=audit_runtime(tmp_path);runtime.membership.admit_atomic(['C','D'])
    runtime.scheduler.begin_startup(['C']);runtime.delegations.prepare('C','initial',source='runtime_startup')
    runtime._release();assert runtime.scheduler.permit()['actor_id']=='C'
    invocation=runtime._next_invocation('C')
    runtime.delegations.complete(invocation['invocation_id'],stage_id='ask',epoch=0,
        request_id='actual-C',terminal_status='completed_via_peer')
    future=Future();future.set_result({'response':{'stopReason':'toolUse'}})
    runtime._settle(future,{future:('C',invocation)})
    assert runtime.scheduler.startup['C']['status']=='initial_invocation_completed'
    assert runtime.scheduler.final_allowed()
    assert 'C' in runtime.scheduler.continuations
