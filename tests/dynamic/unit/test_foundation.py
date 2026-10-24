import json
import pytest
from trustfork.runtime.dynamic.common import DynamicError, repo_root, read_json
from trustfork.runtime.dynamic.case_loader import load_case, verify_source_asset, BASE_COMMIT
from trustfork.runtime.dynamic.events import EventLedger, EvidenceStore
from trustfork.runtime.dynamic.operations import OperationStore
from trustfork.runtime.dynamic.schema import score_record, validate_bindings
from trustfork.runtime.dynamic.lifecycle import Lifecycle


def test_catalog_original_hash_and_stage_contracts():
    catalog = read_json(repo_root() / 'trustfork/config/dynamic/cases.json')
    assert len(catalog) == 30
    assert all(c['readiness']['assets'] == 'pass' and not c['errors'] for c in catalog.values())
    memory = load_case('p028')
    chain = load_case('p024')
    assert [(x['id'], x['new_session']) for x in memory['stages']] == [('ask', False)]
    assert len(chain['stages']) == 3 and chain['stages'][-1]['new_session'] is True
    assert {memory['scenario_id'], chain['scenario_id']}.__len__() == 2


def test_errata_never_accept_third_hash(tmp_path):
    root = repo_root()
    task = root / load_case('p001')['source_task_path']
    with pytest.raises(DynamicError, match='asset_hash_mismatch'):
        verify_source_asset(root, task, 'workflow/images/official/mock-api/app.py', '0' * 64)


def test_operation_ack_loss_reuses_result_never_replays(tmp_path):
    store = OperationStore(tmp_path / 'op.sqlite')
    assert store.claim('write-1', {'data': 'first'}) == {'cached': False}
    store.finish('write-1', {'written': 5})
    assert store.claim('write-1', {'data': 'first'}) == {'cached': True, 'result': {'written': 5}}
    with pytest.raises(DynamicError, match='operation_id_reused'):
        store.claim('write-1', {'data': 'second'})
    store.claim('crashed', {'command': 'effect'})
    store.close()
    restored = OperationStore(tmp_path / 'op.sqlite')
    with pytest.raises(DynamicError, match='operation_effect_unknown'):
        restored.claim('crashed', {'command': 'effect'})
    restored.close()


def test_concurrent_observation_is_ambiguous(tmp_path):
    store = OperationStore(tmp_path / 'op.sqlite')
    store.claim('a', {})
    store.claim('b', {})
    assert store.finish('a', {})['overlapping_operation_ids'] == ['b']
    assert store.finish('b', {})['overlapping_operation_ids'] == ['a']
    store.close()


def test_event_identity_integrity_and_reference_scope(tmp_path):
    ledger = EventLedger(tmp_path / 'events.jsonl', 'branch', 'p001')
    a = ledger.append('message', {'body': 'same'})
    b = ledger.append('message', {'body': 'same'})
    assert a['event_id'] != b['event_id']
    assert len(EventLedger(ledger.path, 'branch', 'p001').rows) == 2
    with pytest.raises(DynamicError, match='cross_branch_event'):
        EventLedger(ledger.path, 'other', 'p001')
    evidence = EvidenceStore(tmp_path / 'evidence', 'branch')
    ref = evidence.put({'private': 'fixture'})
    with pytest.raises(DynamicError, match='cross_branch_reference'):
        evidence.get(ref, branch_id='other')
    data = ledger.path.read_text().replace('same', 'changed', 1)
    ledger.path.write_text(data)
    with pytest.raises(DynamicError, match='invalid_event_ledger'):
        EventLedger(ledger.path, 'branch', 'p001')


def test_unknown_is_not_safe_zero_and_unresolved_api_fails():
    assert score_record('TH', None, 'unknown')['value'] is None
    with pytest.raises(DynamicError):
        score_record('TH', 0, 'unknown')
    config = read_json(repo_root() / 'trustfork/config/dynamic/model_bindings.example.json')
    assert not validate_bindings(config, formal=False)['formal_ready']
    with pytest.raises(DynamicError, match='unresolved_formal_bindings'):
        validate_bindings(config, formal=True)


def test_initial_barrier_and_transition_rejection(tmp_path):
    life = Lifecycle(EventLedger(tmp_path / 'events', 'b', 'p001'))
    assert not life.worker_permitted()
    for state in ['PLAN_READY', 'JOINING', 'COORDINATING']:
        life.transition(state)
        assert not life.worker_permitted()
    life.transition('RUNNING')
    assert life.worker_permitted()
    with pytest.raises(DynamicError, match='invalid_lifecycle_transition'):
        life.transition('SCORING')
