import json
from pathlib import Path
import pytest
from trustfork.agents.pi_dynamic import PiDynamic,ScriptSource
from trustfork.runtime.dynamic.scripted_fixtures import branch_scripts
from trustfork.runtime.dynamic.common import read_json
from trustfork.runtime.dynamic.environment import DockerEnvironment


@pytest.mark.parametrize('case_id',['p004','p006','p008','p028'])
def test_late_join_restores_actual_old_member_work_in_four_original_cases(tmp_path,case_id):
    engine=PiDynamic(case_id,tmp_path/case_id,protocol='L')
    result=engine.run_block(ScriptSource(branch_scripts(case_id,protocol='L')),conditions=('HP',))
    assert result['branches'][0]['run_status']=='valid_behavior'
    checkpoint=read_json(tmp_path/case_id/'late-prefix/checkpoint.json')
    files={row['path'].removeprefix('./') for row in DockerEnvironment.archive_fingerprint(
        Path(checkpoint['environment']['workspace_export']['workspace_tar']).read_bytes())}
    assert 'late-prefix-A.txt' in files and 'late-prefix-B.txt' in files
    assert checkpoint['lifecycle_state']=='RUNNING' and not checkpoint['scheduler']['active']
    prefix=checkpoint['prefix_events']
    trigger=[e for e in prefix if e['event_type']=='late_join_trigger']
    assert len(trigger)==1
    assert trigger[0]['payload']['kind']=='first_old_member_tool_return'
    assert any(e['event_type']=='tool_operation_finished' and e['actor_id'] in ('A','B') for e in prefix)
    run=result['branches'][0];manifest=read_json(tmp_path/case_id/'HP/attempt-0/run_manifest.json')
    assert run['checkpoint_id']==checkpoint['checkpoint_id'] and manifest['asset_hash']
    assert run['environment_verification']['status']=='verified_restored'
    assert run['real_model_requests']==run['real_judge_requests']==0
