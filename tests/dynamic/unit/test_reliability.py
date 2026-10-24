import pytest
from trustfork.runtime.dynamic.budget import Budget
from trustfork.runtime.dynamic.common import DynamicError
from trustfork.runtime.dynamic.reliability import TransportFailure,transport_request,judge_request,branch_attempts
from trustfork.runtime.dynamic.profile_service import ProfileService,build_profile,REMINDER


def test_transport_first_plus_two_attempts_and_refusal_is_never_retried():
    budget=Budget();calls=[]
    def operation(attempt):
        calls.append(attempt['attempt_id'])
        if len(calls)<3:raise TransportFailure('http_429',output_tokens=0)
        return {'status':'success','output_tokens':2,'response':'refusal'}
    result=transport_request(operation,budget=budget,request_id='logical',actor_id='C')
    assert result['response']=='refusal' and calls==['logical.attempt0','logical.attempt1','logical.attempt2']
    assert budget.output_tokens==2 and len(budget.attempts)==3
    exhausted=Budget()
    with pytest.raises(TransportFailure):
        transport_request(lambda attempt:(_ for _ in ()).throw(TransportFailure('disconnect',output_tokens=0)),
            budget=exhausted,request_id='r',actor_id='C')
    assert len(exhausted.attempts)==3


@pytest.mark.parametrize('generated,effects',[(True,False),(False,True),(True,True)])
def test_transport_never_repeats_generation_or_side_effects(generated,effects):
    budget=Budget()
    with pytest.raises(DynamicError,match='transport_effect_unknown'):
        transport_request(lambda attempt:(_ for _ in ()).throw(TransportFailure('disconnect',
            generation_received=generated,tool_effects_started=effects,output_tokens=None)),
            budget=budget,request_id='r',actor_id='D')
    assert len(budget.attempts)==1 and budget.output_tokens==4096


def test_judge_failure_preserves_trajectory_and_branch_failure_bound():
    log=[];calls=[]
    def judge(number):calls.append(number);raise TimeoutError('fixture')
    outcome=judge_request(judge,validate=lambda value:None,attempt_log=log)
    assert calls==[0,1,2] and outcome['status']=='judge_error' and outcome['value'] is None
    failures=[];branch=[]
    def infrastructure(attempt):
        branch.append(attempt)
        if attempt==0:raise DynamicError('fixture_infra','only retry condition')
        return {'run_status':'valid_behavior','refusal':True}
    assert branch_attempts(infrastructure,retryable_codes={'fixture_infra'},failures=failures)['refusal']
    assert branch==[0,1] and len(failures)==1


def test_reminder_is_exact_opt_in_and_covers_all_public_queries():
    bundles={'C':build_profile('C','H')}
    normal=ProfileService('b',bundles);reminder=ProfileService('b',bundles,reminder=True)
    for method,args in [('get_public_profile',('C','summary')),('get_public_profile',('C','records')),
        ('get_public_profile',('C','full')),('get_profile_record',('profile://C/records/01',)),
        ('get_work_sample',('profile://C/work-samples/01',)),('get_profile_statistics',('C','family')),
        ('get_profile_statistics',('C','recent')),('get_historical_config',('history_config_C_v1',))]:
        original=getattr(normal,method)(*args);wrapped=getattr(reminder,method)(*args)
        if isinstance(original,list):
            assert all(x['notice']==REMINDER and x['safety_assessed'] is False for x in wrapped)
            stripped=[{k:v for k,v in x.items() if k not in ('notice','safety_assessed')} for x in wrapped]
        else:
            assert wrapped.pop('notice')==REMINDER and wrapped.pop('safety_assessed') is False
            stripped=wrapped
        assert stripped==original
    assert normal.bundles==reminder.bundles
