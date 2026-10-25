import copy
import pytest
from trustfork.runtime.dynamic.common import DynamicError,digest
from trustfork.runtime.dynamic.model_capabilities import unknown_capability,validate_capability
from trustfork.scoring.judge_request import prepare_judge_request,capacity_report
from trustfork.scoring.trajectory_codec import encode_trajectory

BINDING={'provider':'synthetic','base_url':'fixture://capacity','model_id':'synthetic-model'}


def prepared(output=4096):
    return prepare_judge_request({'private_goals_removed':True,'trajectory':[]},rubric='original rubric',
        format_instructions='return the specified anchors',output_budget=output,tools=[{'name':'example'}],
        parameters={'temperature':0},counter=lambda s:len(s),judge_binding=BINDING)


def capability(limit=100000):
    return {'status':'verified','effective_context_tokens':limit,'max_output_tokens':16000,
        'source':'synthetic://capacity-fixture','evidence_hash':digest('fixture'),'verified_at':'2026-10-25',
        'route_fingerprint':digest(BINDING),'tokenizer':{'id':'synthetic-character-counter',
        'version':'1','count_method':'fixture-exact','applicable_route':digest(BINDING)},
        'framing_tokens':0,'output_token_parameter':'max_tokens'}


def test_prepared_request_binds_every_sent_field_and_reserves_independent_output():
    p=prepared(); assert p['request_hash']==digest(p['request'])
    assert p['request']['messages'][0]['content'].startswith('original rubric')
    assert p['request']['tools']==[{'name':'example'}]
    assert p['output_budget']==4096 and p['request']['parameters']['max_tokens']==4096
    report=capacity_report(p,capability()); assert report['fits'] and report['capacity_status']=='verified'
    assert not report['can_send'] and report['sender_enabled'] is False


def test_http_json_escaping_is_not_charged_as_model_content():
    view={'private_goals_removed':True,'trajectory':[{'text':'"\\\n'*1000}]}
    p=prepare_judge_request(view,rubric='rubric',format_instructions='format',output_budget=4096,counter=len,judge_binding=BINDING)
    assert p['input_tokens']==sum(len(m['content']) for m in p['request']['messages'])
    assert p['wire_serialization_tokens']>p['input_tokens']
    assert p['wire_tokens_are_model_input_tokens'] is False
    assert p['output_budget']==4096 and p['tool_and_format_schema_tokens']==0
    assert p['input_tokens']+4096<11000<p['wire_serialization_tokens']+4096
    assert capacity_report(p,capability(11000))['fits'] is True


@pytest.mark.parametrize('kind',['unknown','declared','overflow','output_limit','output_unknown','framing_unknown','counter_unknown','route_mismatch'])
def test_capacity_blocks_without_silently_truncating_or_changing_model(kind):
    p=prepared(); c=capability()
    if kind=='unknown':c=unknown_capability()
    if kind=='declared':c['status']='declared'
    if kind=='overflow':c['effective_context_tokens']=10
    if kind=='output_limit':c['max_output_tokens']=10
    if kind=='output_unknown':p=prepared(None)
    if kind=='framing_unknown':c['framing_tokens']=None
    if kind=='counter_unknown':p['input_tokens']=None
    if kind=='route_mismatch':p['route_fingerprint']=digest('wrong route')
    old=copy.deepcopy(p['request']); report=capacity_report(p,c)
    assert not report['can_send'] and report['reason'] in {'capacity_unknown','capacity_blocked'}
    assert p['request']==old
    assert report['behavior_run_status']=='unchanged' and report['score_status']=='judge_error'


def test_effective_capacity_requires_route_specific_evidence_and_does_not_infer_alias():
    c=capability(); c['source']=None
    with pytest.raises(DynamicError):validate_capability(c)
    assert unknown_capability()['effective_context_tokens'] is None


def test_complete_alias_fields_cannot_enable_formal_without_effective_count_evidence():
    from trustfork.runtime.dynamic.common import read_json,config_dir
    from trustfork.runtime.dynamic.schema import validate_bindings
    # Pure in-memory negative fixture, never used as runtime configuration.
    config=read_json(config_dir()/'model_bindings.example.json')
    config.update(mode='api',real_api_enabled=True)
    for binding in config['logical_bindings'].values():
        binding.update(BINDING,key_env='UNUSED_SYNTHETIC_KEY_ENV',context_window=128000,
            max_output_tokens=16000,supported_parameters=['max_tokens'])
        c=capability();c['framing_tokens']=None;binding['capability']=c
    assert not validate_bindings(config,formal=False)['formal_ready']
    with pytest.raises(DynamicError,match='unresolved_formal_bindings'):validate_bindings(config,formal=True)


def test_cache_miss_cannot_download_tokenizer_or_probe_endpoint(tmp_path,monkeypatch):
    from trustfork.scoring.judge_request import offline_counter
    import tiktoken.load
    offline_counter.cache_clear();monkeypatch.setenv('TIKTOKEN_CACHE_DIR',str(tmp_path))
    def forbidden(*a,**k):pytest.fail('Attempted tokenizer network/download')
    monkeypatch.setattr(tiktoken.load,'read_file',forbidden)
    with pytest.raises(DynamicError,match='offline_tokenizer_unavailable'):offline_counter()
    offline_counter.cache_clear()


def test_long_complete_request_keeps_behavior_and_blocks_judge():
    p=prepare_judge_request({'private_goals_removed':True,'trajectory':[{'body':'a'*130000}]},
        rubric='rubric',format_instructions='JSON',output_budget=4096,counter=len)
    c=capability(128000); report=capacity_report(p,c)
    assert report['reason']=='capacity_blocked' and report['behavior_run_status']=='unchanged'
    assert p['request']['messages'][1]['content'].count('a')>=130000
