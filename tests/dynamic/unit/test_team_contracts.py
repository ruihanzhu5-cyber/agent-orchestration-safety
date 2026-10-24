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
    first=budget.reserve('r',0);second=budget.reserve('s',0)
    assert first['max_output_tokens']==6 and second['max_output_tokens']==4
    assert not budget.available()
    budget.finish(first['attempt_id'],output_tokens=2,status='success')
    assert budget.available()
    restored=Budget.restore(budget.snapshot())
    assert restored.output_tokens==2 and len(restored.attempts)==2
    with pytest.raises(DynamicError,match='transport_retry_limit'):
        restored.reserve('r',3)
