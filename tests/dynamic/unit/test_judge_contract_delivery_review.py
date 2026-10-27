"""Production-path regressions and replay of the unchanged paid failure."""
import copy
import json
from collections import deque
import pytest
from trustfork.runtime.dynamic.common import DynamicError, repo_root, read_json, file_hash, config_dir
from trustfork.runtime.dynamic.provider import ProviderTransport
from trustfork.scoring.formal_judge_fixtures import make_fixture, fixture_metrics
from trustfork.scoring.judge_contract import validate_complete_result
from trustfork.scoring.judge_request import prepare_judge_pass, build_judge_bundle
from trustfork.scoring.judge_client import JudgeClient
from trustfork.scoring.trajectory_observer import event_ref
from test_formal_judge_followup import oracle_annotations
from test_provider_preparation import configuration
from test_first_api_judge import reply


def setup(tmp_path):
    fixture = make_fixture(tmp_path, 'direct_failed_attempt')
    config = configuration()
    config['logical_bindings']['gpt4o']['max_output_tokens'] = 16384
    config['logical_bindings']['gpt4o']['capability']['max_output_tokens'] = 16384
    prepared = prepare_judge_pass(fixture['bundle'], 'trajectory',
        binding=config['logical_bindings']['gpt4o'],
        scorer_config={'trajectory_output_budget_tokens': 16384}, counter=len)
    return fixture, config, prepared


@pytest.mark.parametrize('mutation,code', [('missing_member', 'opportunity_coverage_missing'),
    ('missing_action_binding', 'unsafe_attempt_action_invalid'),
    ('effect_conflict', 'attempt_effect_conflict')])
def test_single_contract_failure_gets_one_repair_without_fact_answers(tmp_path, mutation, code):
    fixture, config, prepared = setup(tmp_path)
    good = oracle_annotations(fixture)
    bad = copy.deepcopy(good)
    if mutation == 'missing_member':
        bad['opportunity_annotations'] = [r for r in bad['opportunity_annotations'] if r['actor_id'] == 'A']
    elif mutation == 'missing_action_binding':
        bad['unsafe_attempt_annotations'][0].pop('action_id')
    else:
        bad['action_annotations'][0]['effect_status'] = 'observed'
    sent = []
    responses = deque([reply(json.dumps(bad)), reply(json.dumps(good))])
    def http(url, body, *args):
        sent.append(json.loads(body))
        return responses.popleft()
    transport = ProviderTransport(config, mode='mock', journal=tmp_path/'judge.jsonl',
        kind='judge', max_requests=2, http=http)
    result = JudgeClient(transport).send_with_repair(prepared, request_id='contract',
        pass_name='trajectory', evidence_refs={event_ref(e) for e in fixture['events']},
        validation_context={'events': fixture['events']})
    assert result['structure_attempts'] == 2 and transport.count == 2
    repair = sent[1]['messages'][-1]['content']
    assert code in repair and 'oracle' not in repair and 'expected_score' not in repair
    assert json.loads(sent[1]['messages'][-2]['content']) == bad


def test_new_contract_accepts_explicit_unknown_not_missing(tmp_path):
    fixture, config, prepared = setup(tmp_path)
    value = oracle_annotations(fixture)
    for row in value['opportunity_annotations']:
        row.update(opportunity_state='unknown', status='unknown', anchor=None,
            visible_request_ref=None, decision_ref=None, evidence_refs=[])
    validate_complete_result(value, prepared=prepared, events=fixture['events'],
        pass_name='trajectory', scoring_profile='dynamic-homogeneous-v2',
        evidence_refs={event_ref(e) for e in fixture['events']})
    assert fixture_metrics(fixture, value)['opportunities']['SAF_visible']['value'] is None


def test_fixture_main_final_has_actual_input(tmp_path):
    fixture, _, _ = setup(tmp_path)
    requests = {(e['actor_id'], e['request_id']) for e in fixture['events'] if e['event_type'] == 'model_request_submitted'}
    assert all((e['actor_id'], e['request_id']) in requests for e in fixture['events'] if e['event_type'] == 'model_response')


def test_retained_paid_failure_rejected_without_rewriting_it():
    root = repo_root()/'runs/published/runtime-judge-review-20261026/evidence/fixtures/direct_failed_attempt'
    source_path = root/'source.json'
    result_path = root/'trajectory-lossless-v1/result.json'
    before = (file_hash(source_path), file_hash(result_path))
    source = read_json(source_path)
    value = read_json(result_path)['result']
    views = source['bundle']['views']
    bundle = build_judge_bundle(views['response'], views['trajectory']['trajectory_view'],
        scoring_profile='dynamic-homogeneous-v2',
        annotation_schema=read_json(config_dir()/'annotation.schema.json'))
    prepared = prepare_judge_pass(bundle, 'trajectory',
        binding=configuration()['logical_bindings']['gpt4o'],
        scorer_config={'trajectory_output_budget_tokens': 16384}, counter=len)
    with pytest.raises(DynamicError, match='judge_contract_relationship_errors') as error:
        validate_complete_result(value, prepared=prepared, events=source['events'],
            pass_name='trajectory', scoring_profile='dynamic-homogeneous-v2',
            evidence_refs={event_ref(e) for e in source['events']})
    paths = [row['path'] for row in error.value.evidence['errors']]
    assert '$.opportunity_annotations' in paths
    assert any('action_id' in path for path in paths)
    assert before == (file_hash(source_path), file_hash(result_path))
