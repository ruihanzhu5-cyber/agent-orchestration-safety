"""Regression cases for opportunity evidence and explicit missingness semantics."""
import copy
import pytest

from trustfork.runtime.dynamic.common import DynamicError
from trustfork.scoring.formal_judge_fixtures import make_fixture
from trustfork.scoring.dynamic_metrics_v2 import opportunity_scores
from test_formal_judge_followup import oracle_annotations


def fixture(tmp_path):
    source = make_fixture(tmp_path, 'direct_failed_attempt')
    rows = oracle_annotations(source)['opportunity_annotations']
    return source['events'], rows


def active(rows):
    return next(r for r in rows if r['actor_id'] == 'A' and r['metric_id'] == 'SAF_visible')


@pytest.mark.parametrize('status,anchor', [('judge_error', None), ('not_applicable', 5), ('complete', 0)])
def test_absence_cannot_hide_judge_error_or_score(tmp_path, status, anchor):
    events, rows = fixture(tmp_path)
    row = next(r for r in rows if r['actor_id'] == 'B' and r['metric_id'] == 'SAF_visible')
    row.update(status=status, anchor=anchor)
    with pytest.raises(DynamicError, match='opportunity_state_invalid'):
        opportunity_scores(rows, events, 'C')


def test_unknown_cannot_keep_complete_score(tmp_path):
    events, rows = fixture(tmp_path)
    active(rows)['opportunity_state'] = 'unknown'
    with pytest.raises(DynamicError, match='opportunity_state_invalid'):
        opportunity_scores(rows, events, 'C')


@pytest.mark.parametrize('decision_type', ['model_request_submitted', 'pi_event', 'workspace_state_observation'])
def test_input_stream_draft_and_state_observation_are_not_decisions(tmp_path, decision_type):
    events, rows = fixture(tmp_path)
    row = active(rows)
    event = next(e for e in events if e['actor_id'] == 'A' and e['event_type'] == decision_type)
    reference = event['branch_id'] + '::' + event['event_id']
    row.update(decision_ref=reference, evidence_refs=[row['visible_request_ref'], reference])
    with pytest.raises(DynamicError, match='opportunity_visibility_invalid'):
        opportunity_scores(rows, events, 'C')


def test_declared_epoch_must_match_actual_input(tmp_path):
    events, rows = fixture(tmp_path)
    active(rows)['stage_epoch'] = 99
    with pytest.raises(DynamicError, match='opportunity_visibility_invalid'):
        opportunity_scores(rows, events, 'C')


def test_failed_model_response_is_not_a_completed_decision(tmp_path):
    events, rows = fixture(tmp_path)
    reference = active(rows)['decision_ref']
    event = next(e for e in events if e['branch_id'] + '::' + e['event_id'] == reference)
    event['payload']['status'] = 'error'
    with pytest.raises(DynamicError, match='opportunity_visibility_invalid'):
        opportunity_scores(rows, events, 'C')


def test_duplicate_opportunity_cannot_change_weight(tmp_path):
    events, rows = fixture(tmp_path)
    rows.append(copy.deepcopy(active(rows)))
    with pytest.raises(DynamicError, match='opportunity_duplicate'):
        opportunity_scores(rows, events, 'C')


def test_new_contract_requires_actor_metric_coverage_without_filling_it(tmp_path):
    from trustfork.scoring.dynamic_metrics_v2 import validate_opportunity_annotations
    events, rows = fixture(tmp_path)
    partial = [r for r in rows if r['actor_id'] == 'A']
    before = copy.deepcopy(partial)
    validate_opportunity_annotations(partial, events, require_coverage=False)
    assert opportunity_scores(partial, events, 'C')['SAF_visible']['status'] == 'unknown'
    with pytest.raises(DynamicError, match='opportunity_coverage_missing') as error:
        validate_opportunity_annotations(partial, events, require_coverage=True)
    assert partial == before
    assert error.value.evidence['errors'][0]['path'] == '$.opportunity_annotations'


def test_explicit_unknown_is_legal_but_never_becomes_a_safe_score(tmp_path):
    from trustfork.scoring.dynamic_metrics_v2 import validate_opportunity_annotations
    events, rows = fixture(tmp_path)
    active(rows).update(opportunity_state='unknown', status='unknown', anchor=None, decision_ref=None)
    validate_opportunity_annotations(rows, events, require_coverage=True)
    metric = opportunity_scores(rows, events, 'C')['SAF_visible']
    assert metric['status'] == 'unknown' and metric['value'] is None


def test_multiple_distinct_opportunities_remain_legal(tmp_path):
    from trustfork.scoring.dynamic_metrics_v2 import validate_opportunity_annotations
    events, rows = fixture(tmp_path)
    row = copy.deepcopy(active(rows))
    event = next(e for e in events if e['event_type'] == 'tool_operation_started')
    reference = event['branch_id'] + '::' + event['event_id']
    row.update(decision_ref=reference, evidence_refs=[row['visible_request_ref'], reference])
    rows.append(row)
    validate_opportunity_annotations(rows, events, require_coverage=True)
    assert opportunity_scores(rows, events, 'C')['SAF_visible']['coverage']['A']['opportunities'] == 2
