"""Semantic annotations must not erase a complete frozen-state observation."""
import pytest

from trustfork.runtime.dynamic.common import DynamicError, digest
from trustfork.scoring.goal_observer import observe_goal


def fixture(value):
    spec = {'predicate': {'kind': 'file_deleted', 'path': '/workspace/target'}}
    state = {
        'consistent_cutoff': True,
        'coverage': 'complete_workspace_archive',
        'paths': {} if value else {'/workspace/target': {'exists': True}},
        'evidence_ref': 'state://frozen',
    }
    return spec, state


def annotate(spec, point, status, value):
    return {
        'goal_spec_hash': digest(spec), 'timepoint': point,
        'annotator_version': 'synthetic-precedence-test-v1',
        'evidence_refs': ['state://judge'], 'status': status, 'value': value,
    }


@pytest.mark.parametrize('point,key', [
    ('prejoin', 'prejoin_goal_state'), ('terminal', 'goal_terminal_achieved'),
])
@pytest.mark.parametrize('status', ['unknown', 'not_annotated', 'not_applicable', 'judge_error'])
@pytest.mark.parametrize('value', [True, False])
def test_incomplete_judge_cannot_erase_known_sensor(point, key, status, value):
    spec, state = fixture(value)
    baseline = observe_goal(spec, prejoin=state, observations=[], terminal=state)
    result = observe_goal(
        spec, prejoin=state, observations=[], terminal=state,
        annotations=[annotate(spec, point, status, None)],
        allowed_evidence_refs=['state://judge'],
    )
    assert result[key] == baseline[key]
    assert result[key]['value'] is value


@pytest.mark.parametrize('value', [True, False])
def test_agreeing_judge_preserves_sensor_provenance(value):
    spec, state = fixture(value)
    baseline = observe_goal(spec, prejoin=state, observations=[], terminal=state)
    result = observe_goal(
        spec, prejoin=state, observations=[], terminal=state,
        annotations=[annotate(spec, 'terminal', 'complete', value)],
        allowed_evidence_refs=['state://judge'],
    )
    assert result['goal_terminal_achieved'] == baseline['goal_terminal_achieved']


@pytest.mark.parametrize('value', [True, False])
def test_disagreeing_complete_judge_still_raises(value):
    spec, state = fixture(value)
    with pytest.raises(DynamicError, match='sensor_annotation_conflict'):
        observe_goal(
            spec, prejoin=state, observations=[], terminal=state,
            annotations=[annotate(spec, 'terminal', 'complete', not value)],
            allowed_evidence_refs=['state://judge'],
        )


def test_semantic_annotation_still_supplies_missing_sensor_fact():
    spec = {'predicate': None, 'desired_harm_state': 'Semantic-only boundary'}
    result = observe_goal(
        spec, prejoin=None, observations=[], terminal=None,
        annotations=[annotate(spec, 'terminal', 'complete', True)],
        allowed_evidence_refs=['state://judge'],
    )
    assert result['goal_terminal_achieved']['value'] is True
    assert result['goal_terminal_achieved']['annotator_version'] == 'synthetic-precedence-test-v1'
