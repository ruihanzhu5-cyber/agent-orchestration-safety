import concurrent.futures
import json
import pytest
from trustfork.runtime.dynamic.artifacts import Campaign,append_jsonl,safe_slug
from trustfork.runtime.dynamic.common import DynamicError,read_json


def test_campaign_conflict_verified_resume_and_tamper(tmp_path,monkeypatch):
    monkeypatch.setenv('TRUSTFORK_ARTIFACT_ROOT',str(tmp_path))
    args=dict(commit='abc',config={'x':1},plan=[{'block_id':'a|b:c'}],mode='mock',campaign_id='test')
    campaign=Campaign.create(**args)
    with pytest.raises(DynamicError,match='campaign_exists'):Campaign.create(**args)
    assert Campaign.create(**args,resume=True).path==campaign.path
    with pytest.raises(DynamicError,match='campaign_resume_mismatch'):Campaign.create(**{**args,'commit':'new'},resume=True)
    block=campaign.block('a|b:c');assert '|' not in block.name and ':' not in block.name
    one=campaign.attempt('a|b:c','HP',0);two=campaign.attempt('a|b:c','HA',0)
    assert one!=two
    with pytest.raises(DynamicError,match='attempt_exists'):campaign.attempt('a|b:c','HP',0)
    (one/'run.json').write_text('{"run_id":"run-one"}\n');campaign.index();campaign.verify()
    assert campaign.attempt('a|b:c','HP',0,resume=True)==one
    (one/'run.json').write_text('{}')
    with pytest.raises(DynamicError,match='artifact_hash_mismatch'):campaign.verify()


def test_concurrent_jsonl_and_incomplete_suffix(tmp_path):
    path=tmp_path/'events.jsonl'
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda n:append_jsonl(path,{'n':n}),range(100)))
    rows=[json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows)==100 and len({r['n'] for r in rows})==100
    with path.open('ab') as stream:stream.write(b'{"incomplete":')
    with pytest.raises(DynamicError,match='incomplete_jsonl_suffix'):append_jsonl(path,{'n':'new'})


def test_seal_keeps_originals_and_verifies_index(tmp_path,monkeypatch):
    monkeypatch.setenv('TRUSTFORK_ARTIFACT_ROOT',str(tmp_path/'root'))
    campaign=Campaign.create(commit='abc',config={},plan=[],mode='mock',campaign_id='seal')
    campaign.finish('failed')
    assert read_json(campaign.path/'campaign.json')['status']=='failed'
    archive=campaign.seal(tmp_path/'backup/campaign.tar.gz')
    assert archive.is_file() and (campaign.path/'campaign.json').is_file()
    with pytest.raises(DynamicError,match='archive_exists'):campaign.seal(archive)
    assert safe_slug('CON').startswith('block-')
