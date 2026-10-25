import sys
import pytest
from trustfork.runtime.dynamic.artifacts import Campaign
from trustfork.runtime.dynamic.common import DynamicError
from trustfork.tools.run_dynamic import main
def test_new_source_cannot_run_under_old_campaign_identity(tmp_path,monkeypatch):
 monkeypatch.setenv('TRUSTFORK_ARTIFACT_ROOT',str(tmp_path))
 campaign=Campaign.create(commit='different-source',config={},plan=[],mode='scripted-test',campaign_id='old')
 monkeypatch.setattr(sys,'argv',['run_dynamic','--mode','scripted-test','--case','p001','--protocol','S','--team-model','gpt4o','--history-bundle',str(tmp_path/'not-read.json'),'--campaign','old'])
 with pytest.raises(DynamicError,match='campaign_invocation_mismatch'):main()
 assert not list((campaign.path/'blocks').iterdir())
