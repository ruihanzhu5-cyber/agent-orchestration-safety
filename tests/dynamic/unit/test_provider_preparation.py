import copy
import json
import pytest
from trustfork.runtime.dynamic.common import DynamicError,digest,read_json
from trustfork.runtime.dynamic.provider import ProviderTransport,resolve_provider
from trustfork.scoring.judge_client import JudgeClient,validate_judge_result
from trustfork.scoring.judge_request import prepare_judge_request,capacity_report


def configuration():
    binding={'provider':'synthetic','base_url':'https://mock.invalid/v1','model_id':'exact-fixture','key_env':'UNUSED_FIXTURE_KEY',
        'context_window':128000,'max_output_tokens':4096,'supported_parameters':['temperature','max_tokens'],
        'api':'openai-completions','compat':{k:False for k in ('supportsStore','supportsDeveloperRole','supportsReasoningEffort',
        'supportsUsageInStreaming','supportsFinishReason','requiresToolResultName','requiresAssistantAfterToolResult','requiresThinkingAsText',
        'requiresReasoningContentOnAssistantMessages','supportsStrictMode')},'output_token_parameter':'max_tokens'}
    route=digest({k:binding[k] for k in ('provider','base_url','model_id')})
    binding['capability']={'status':'verified','effective_context_tokens':128000,'max_output_tokens':4096,
        'source':'synthetic://unit-fixture','evidence_hash':digest('fixture'),'verified_at':'2026-10-25','route_fingerprint':route,
        'tokenizer':{'id':'fixture','version':'1','count_method':'fixture-exact','applicable_route':route},'framing_tokens':0,'output_token_parameter':'max_tokens'}
    return {'protocol_version':'dynamic-join-v9-trajectory-portfolio','mode':'offline','real_api_enabled':False,
        'logical_bindings':{a:copy.deepcopy(binding) for a in ('gpt4o','deepseekflash')},'judge_binding':'gpt4o'}


def test_configured_key_does_not_enable_real_transport(tmp_path,monkeypatch):
    monkeypatch.setenv('UNUSED_FIXTURE_KEY','credential-sentinel-only')
    for authorized in (False,True):
        with pytest.raises(DynamicError,match='real_api_disabled'):
            ProviderTransport(configuration(),mode='api',journal=tmp_path/'log',authorize_real=authorized,max_requests=1)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('reply_kind',['success','429','timeout','partial','bad_json'])
def test_mock_attempts_failures_and_credentials_have_a_real_journal(tmp_path,reply_kind):
    config=configuration();calls=[]
    def http(url,body,key,timeout):
        calls.append(url)
        if reply_kind=='timeout':raise TimeoutError('mock timeout')
        return {'status':429 if reply_kind=='429' else 200,'headers':{'authorization':'must-not-log','x-request-id':'provider-id'},
            'body':'mock-no-credential' if reply_kind=='bad_json' else '{"usage":{"completion_tokens":2}}','read_error':reply_kind=='partial'}
    transport=ProviderTransport(config,mode='mock',journal=tmp_path/'attempts.jsonl',http=http,max_requests=2)
    wire={'url':'https://mock.invalid/v1/chat/completions','method':'POST','body':json.dumps({'model':'exact-fixture','messages':[]})}
    for request_id in ('first','second'):
        try:transport.request('gpt4o',wire,request_id=request_id)
        except DynamicError:assert reply_kind=='timeout'
    with pytest.raises(DynamicError,match='provider_request_budget_exhausted'):transport.request('gpt4o',wire,request_id='third')
    rows=[json.loads(line) for line in (tmp_path/'attempts.jsonl').read_text().splitlines()]
    assert len(calls)==2 and len(rows)==4
    assert all(r['source']=='mock' and r['synthetic'] is True and r['cost'] is None for r in rows)
    assert 'must-not-log' not in (tmp_path/'attempts.jsonl').read_text()
    assert 'mock-no-credential' not in (tmp_path/'attempts.jsonl').read_text()


def test_no_alias_inference_or_route_fallback(tmp_path):
    config=configuration();config['logical_bindings']['deepseekflash']['model_id']=None
    from trustfork.runtime.dynamic.model_capabilities import unknown_capability
    config['logical_bindings']['deepseekflash']['capability']=unknown_capability()
    with pytest.raises(DynamicError,match='unresolved_provider_binding'):resolve_provider(config,'deepseekflash')
    transport=ProviderTransport(config,mode='mock',journal=tmp_path/'log',http=lambda *a:pytest.fail('Must not send'),max_requests=1)
    for body in ({'model':'fallback'},{'model':'exact-fixture'}):
        with pytest.raises(DynamicError):transport.request('gpt4o',{'url':'https://wrong.invalid','method':'POST','body':json.dumps(body)},request_id='r')


def test_judge_exact_payload_and_unknown_capacity_gate(tmp_path):
    config=configuration();binding=config['logical_bindings']['gpt4o'];sent=[]
    result={'trajectory_judgements':{k:{'value':1,'status':'complete','evidence_refs':['event://fixture']} for k in ('ias','saf','vf','ei','terminal_safety','task_utility')}}
    def http(url,body,key,timeout):
        sent.append(json.loads(body))
        return {'status':200,'headers':{'content-type':'application/json'},'body':json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(result)}}]})}
    transport=ProviderTransport(config,mode='mock',journal=tmp_path/'judge.jsonl',http=http,max_requests=2,kind='judge')
    prepared=prepare_judge_request({'private_goals_removed':True,'events':[]},rubric='original',format_instructions='json',
        output_budget=100,counter=len,judge_binding=binding)
    answer=JudgeClient(transport).send(prepared,request_id='j',pass_name='trajectory',evidence_refs=['event://fixture'])
    assert answer['synthetic'] and sent==[prepared['wire_payload']]
    bad=copy.deepcopy(prepared);bad['wire_payload']['unaccounted']='hidden extra'
    with pytest.raises(DynamicError,match='judge_request_hash_mismatch'):JudgeClient(transport).send(bad,request_id='bad',pass_name='trajectory')
    config['logical_bindings']['gpt4o']['capability']['framing_tokens']=None
    with pytest.raises(DynamicError,match='capacity_unknown'):JudgeClient(transport).send(prepared,request_id='unknown',pass_name='trajectory')
    assert len(sent)==1


def test_judge_just_fits_one_token_over_and_output_only_overflow():
    binding=configuration()['logical_bindings']['gpt4o'];p=prepare_judge_request({},rubric='r',format_instructions='f',output_budget=5,counter=len,judge_binding=binding)
    capability=copy.deepcopy(binding['capability']);capability['effective_context_tokens']=p['input_tokens']+5
    assert capacity_report(p,capability,sender_enabled=True,mode='api',authorized=True)['can_send']
    capability['effective_context_tokens']-=1
    assert capacity_report(p,capability)['reason']=='capacity_blocked'
    capability['effective_context_tokens']=100000;capability['max_output_tokens']=4
    assert capacity_report(p,capability)['reason']=='capacity_blocked'


def test_judge_rejects_queue_receipts_invalid_refs_and_truncation_schema():
    with pytest.raises(DynamicError):validate_judge_result({'status':'queued'},pass_name='response',response_ids=['delivery'],evidence_refs=[])
    with pytest.raises(DynamicError,match='judge_evidence_invalid'):
        validate_judge_result({'response_judgements':{'delivery':{'status':'complete','rtf':0,'rsr':0,'evidence_refs':['invented']}}},
            pass_name='response',response_ids=['delivery'],evidence_refs=['actual'])


def test_even_explicit_api_mode_requires_separate_limits_before_any_transport(tmp_path,monkeypatch):
    import trustfork.runtime.dynamic.provider as provider
    monkeypatch.setattr(provider,'real_http',lambda *a:pytest.fail('Must not perform external HTTP'))
    config=configuration();config.update(mode='api',real_api_enabled=True)
    with pytest.raises(DynamicError,match='execution_limits_unknown'):
        ProviderTransport(config,mode='api',journal=tmp_path/'log',authorize_real=True,max_requests=1)
    assert not (tmp_path/'log').exists()
