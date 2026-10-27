"""One repair sees independent contract defects without factual oracle hints."""
import copy
import json
from collections import deque

import pytest

from trustfork.runtime.dynamic.common import DynamicError
from trustfork.runtime.dynamic.provider import ProviderTransport
from trustfork.scoring.formal_judge_fixtures import make_fixture
from trustfork.scoring.judge_client import JudgeClient
from trustfork.scoring.judge_contract import validate_complete_result
from trustfork.scoring.judge_request import prepare_judge_pass
from trustfork.scoring.trajectory_observer import event_ref
from test_first_api_judge import reply
from test_formal_judge_followup import oracle_annotations
from test_provider_preparation import configuration


def fixture(tmp_path):
    source = make_fixture(tmp_path, 'direct_failed_attempt')
    value = oracle_annotations(source)
    # Offline expected values stay in test memory, never in Judge requests.
    broken = copy.deepcopy(value)
    broken['opportunity_annotations'] = [
        row for row in broken['opportunity_annotations'] if row['actor_id'] == 'A'
    ]
    broken['unsafe_attempt_annotations'][0].pop('action_id')
    config = configuration()
    config['execution_scope'] = 'engineering_smoke'
    binding = config['logical_bindings']['gpt4o']
    binding['capability']['status'] = 'declared'
    binding['max_output_tokens'] = 16384
    binding['capability']['max_output_tokens'] = 16384
    prepared = prepare_judge_pass(
        source['bundle'], 'trajectory', binding=binding,
        scorer_config={'trajectory_output_budget_tokens': 16384,
                       'trajectory_representation': 'trajectory-lossless-v2'},
    )
    return source, value, broken, config, prepared


def test_independent_missing_rows_and_action_binding_reported_together(tmp_path):
    source, _, broken, _, prepared = fixture(tmp_path)
    before = copy.deepcopy(broken)
    with pytest.raises(DynamicError, match='judge_contract_relationship_errors') as error:
        validate_complete_result(
            broken, pass_name='trajectory', scoring_profile='dynamic-homogeneous-v2',
            evidence_refs={event_ref(e) for e in source['events']},
            events=source['events'], prepared=prepared,
        )
    errors = error.value.evidence['errors']
    assert {item['path'] for item in errors} == {
        '$.opportunity_annotations', '$.unsafe_attempt_annotations[0].action_id',
    }
    assert broken == before
    serialized = json.dumps(errors)
    assert 'terminal_safety' not in serialized
    assert 'offline-fixture-oracle' not in serialized
    assert 'TH_conversion' not in serialized


@pytest.mark.parametrize('repair_valid', [True, False])
def test_single_repair_receives_both_errors_without_oracle(tmp_path, repair_valid):
    source, value, broken, config, prepared = fixture(tmp_path)
    original = copy.deepcopy(broken)
    responses = deque([reply(json.dumps(broken)), reply(json.dumps(value if repair_valid else broken))])
    sent = []

    def http(url, body, *args):
        sent.append(json.loads(body))
        return responses.popleft()

    transport = ProviderTransport(
        config, mode='mock', journal=tmp_path/'judge.jsonl',
        http=http, max_requests=3, kind='judge',
    )
    arguments = dict(
        request_id='combined-contract', pass_name='trajectory',
        evidence_refs={event_ref(e) for e in source['events']},
        validation_context={'events': source['events']},
    )
    if repair_valid:
        result = JudgeClient(transport).send_with_repair(prepared, **arguments)
        assert result['structure_attempts'] == 2
        assert result['result'] == value
    else:
        with pytest.raises(DynamicError, match='judge_contract_relationship_errors'):
            JudgeClient(transport).send_with_repair(prepared, **arguments)
    assert transport.count == 2
    assert not responses
    assert sent[1]['messages'][:2] == sent[0]['messages']
    assert json.loads(sent[1]['messages'][-2]['content']) == original
    feedback = sent[1]['messages'][-1]['content']
    assert '$.opportunity_annotations' in feedback
    assert '$.unsafe_attempt_annotations[0].action_id' in feedback
    assert 'offline-fixture-oracle' not in feedback
    assert 'TH_conversion' not in feedback
    assert 'terminal_safety' not in feedback
