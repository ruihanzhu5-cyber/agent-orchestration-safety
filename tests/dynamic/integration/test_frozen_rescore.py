import copy
import json
import pytest
from trustfork.agents.pi_dynamic import PiDynamic,ScriptSource
from trustfork.runtime.dynamic.scripted_fixtures import branch_scripts
from trustfork.runtime.dynamic.common import read_json,write_json,file_hash,DynamicError
from trustfork.scoring import dynamic_pipeline as pipeline
from trustfork.scoring.scoring_versions import rescore_contract


def test_frozen_run_cross_scorer_version_keeps_raw_and_old_scores(tmp_path,monkeypatch):
    original=pipeline.scorer_manifest();old={**copy.deepcopy(original),'manifest_hash':'synthetic-origin-scorer'}
    monkeypatch.setattr(pipeline,'scorer_manifest',lambda:old)
    runtime=PiDynamic('p001',tmp_path/'block')
    result=runtime.run_block(ScriptSource(branch_scripts('p001')),conditions=['HP'])
    run=next((tmp_path/'block/HP').rglob('run.json'));root=run.parent
    assert result['branches'][0]['run_status']=='valid_behavior'
    pipeline.score_run(run,mode='test-fixtures')
    pointer=read_json(root/'scoring/current_version.json');raw_hash=file_hash(run)
    frozen_hash=file_hash(root/'run_manifest.json')
    monkeypatch.setattr(pipeline,'scorer_manifest',lambda:original)
    # New scores seal the entire event envelope, including timestamps that are
    # deliberately absent from the public Judge view. This is our own generated
    # negative fixture; restore its exact bytes before the positive rescore.
    event_file=root/'events.jsonl';original_events=event_file.read_bytes()
    try:
        events=[json.loads(line) for line in original_events.splitlines()]
        events[0]['monotonic_ns']+=1
        event_file.write_text(''.join(json.dumps(e)+'\n' for e in events))
        with pytest.raises(DynamicError,match='rescore_frozen_evidence_changed'):
            rescore_contract(run,reason='Envelope tamper must fail before first rescore')
    finally:event_file.write_bytes(original_events)
    contract=rescore_contract(run,reason='Synthetic cross-scorer regression; not a real Judge',annotation_policy='pending')
    pipeline.score_run(run,mode='test-fixtures',rescore=contract)
    new=read_json(root/'scoring/current_version.json')
    assert pointer['version_id']!=new['version_id']
    assert (root/'scoring'/pointer['path']/'scores.json').is_file()
    assert file_hash(run)==raw_hash and file_hash(root/'run_manifest.json')==frozen_hash
    identity=read_json(root/'scoring'/new['path']/'version.json')['identity']
    assert identity['rescore']['frozen_identity']['origin_scorer_hash']=='synthetic-origin-scorer'
    assert identity['rescore']['parent_version_id']==pointer['version_id']
    # Corrupting a frozen archive is rejected before current_version can change.
    archive=read_json(run)['frozen_export']['workspace_tar']
    from pathlib import Path
    with Path(archive).open('ab') as stream:stream.write(b'tampered test fixture')
    with pytest.raises(DynamicError,match='rescore_frozen_evidence_changed|frozen_archive_hash_mismatch'):
        rescore_contract(run,reason='Must refuse changed raw evidence')
    assert read_json(root/'scoring/current_version.json')==new
