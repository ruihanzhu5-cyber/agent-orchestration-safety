"""These tests run the original Docker task services, without a model provider."""
import base64
import io
import json
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from trustfork.runtime.dynamic.case_loader import load_case
from trustfork.runtime.dynamic.environment import DockerEnvironment
from trustfork.runtime.dynamic.common import DynamicError


def encoded(text):
    return base64.b64encode(text.encode()).decode()


@pytest.fixture
def task(tmp_path):
    env = DockerEnvironment(tmp_path / 'p001')
    try:
        env.prepare(load_case('p001'))
        yield env
    finally:
        env.close()


def test_actual_container_operations_mock_and_host_isolation(task, tmp_path):
    assert task.start_services()['status'] == 'running'
    ops = task.exec_work_operation
    ops('fs.mkdir', {'path': '/workspace/checks'}, 'mkdir')
    ops('fs.write', {'path': '/workspace/checks/a.txt', 'data': encoded('Docker_ONLY_41\n')}, 'write')
    assert base64.b64decode(ops('fs.read', {'path': '/workspace/checks/a.txt'}, 'read')['data']) == b'Docker_ONLY_41\n'
    assert ops('fs.stat', {'path': '/workspace/checks'}, 'stat')['isDirectory']
    assert ops('fs.access', {'path': '/workspace/checks/a.txt'}, 'access')['accessible']
    assert 'a.txt' in ops('fs.readdir', {'path': '/workspace/checks'}, 'ls')['entries']
    assert 'checks/a.txt' in ops('fs.glob', {'pattern': '*.txt', 'cwd': '/workspace', 'limit': 100}, 'find')['paths']
    result = ops('process.argv', {'argv': ['rg', 'Docker_ONLY_41', '/workspace/checks'], 'cwd': '/workspace'}, 'grep')
    assert result['exitCode'] == 0 and b'Docker_ONLY_41' in base64.b64decode(result['output'])
    sentinel = tmp_path / 'private-host-answer.txt'
    sentinel.write_text('PRIVATE_CONTROL_SENTINEL')
    result = ops('process.bash', {'command': 'test ! -e ' + str(sentinel) + ' && test ! -e /var/run/docker.sock && echo isolated'}, 'bash')
    assert base64.b64decode(result['output']).strip() == b'isolated'
    inspect = json.loads(task.docker('inspect', task.container).stdout)[0]
    assert inspect['Mounts'] == []
    assert inspect['HostConfig']['NanoCpus'] == 2000000000
    assert inspect['HostConfig']['Memory'] == 4096 * 1024**2
    # An ACK loss cannot append twice.
    args = {'command': "echo once >> /workspace/ack.txt"}
    ops('process.bash', args, 'ack-loss')
    ops('process.bash', args, 'ack-loss')
    assert base64.b64decode(ops('fs.read', {'path': '/workspace/ack.txt'}, 'ack-read')['data']) == b'once\n'


@pytest.mark.parametrize('case_id', ['p001', 'p002', 'p007', 'p024', 'p028'])
def test_source_task_snapshot_restore_after_real_work(tmp_path, case_id):
    first = DockerEnvironment(tmp_path / 'original')
    second = DockerEnvironment(tmp_path / 'restored')
    try:
        first.prepare(load_case(case_id))
        first.exec_work_operation('fs.write', {'path': '/workspace/restore-evidence.txt', 'data': encoded('changed in original task')}, 'change')
        if case_id=='p001':
            first.exec_work_operation('fs.write',{'path':'/opt/mock-api/data/restore-state.txt','data':encoded('SERVICE_STATE_42')},'service-change')
        snapshot = first.checkpoint_state(time.monotonic() + 30)
        first.close()
        restored = second.restore(snapshot)
        assert restored['status'] == 'verified_restored' and restored['ram_saved'] is False
        assert base64.b64decode(second.exec_work_operation('fs.read', {'path': '/workspace/restore-evidence.txt'}, 'verify')['data']) == b'changed in original task'
        if case_id=='p001':
            script="import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/download/restore-state.txt').read().decode())"
            actual=second.exec_work_operation('process.argv',{'argv':['python','-c',script]},'service-verify')
            assert actual['exitCode']==0 and base64.b64decode(actual['output']).strip()==b'SERVICE_STATE_42'
            config=base64.b64decode(second.exec_work_operation('fs.read',{'path':'/opt/mock-api/config.json'},'config-before')['data'])
            second.exec_work_operation('fs.write',{'path':'/opt/mock-api/config.json','data':base64.b64encode(config+b'\n').decode()},'config-changed')
            with pytest.raises(DynamicError,match='restore_unsupported'):
                second.checkpoint_state(time.monotonic()+30)
    finally:
        first.close()
        second.close()


def test_freeze_stops_background_mutation_and_uses_readonly_export(task):
    task.exec_work_operation('process.bash', {'command': '(sleep 1; echo late > /workspace/background.txt; echo late > /opt/mock-api/data/late-state.txt) >/tmp/bg.log 2>&1 &'}, 'background')
    task.quiesce(time.monotonic() + 30)
    task.freeze()
    before = task.export_state()
    frozen_bytes = open(before['workspace_tar'], 'rb').read()
    time.sleep(1.2)
    assert task.docker('cp', task.container + ':/workspace/.', '-', binary=True).stdout == frozen_bytes
    service_before=Path(before['additional_exports']['mock_api']['path']).read_bytes()
    assert task.docker('cp',task.container+':/opt/mock-api','-',binary=True).stdout==service_before
    with pytest.raises(DynamicError, match='environment_not_accepting'):
        task.exec_work_operation('fs.write', {'path': '/workspace/no', 'data': ''}, 'forbidden')
    with tarfile.open(fileobj=io.BytesIO(frozen_bytes)) as archive:
        assert not any(m.name.endswith('background.txt') for m in archive)


def test_original_mock_html_is_served_byte_for_byte_with_ipi_preserved(task):
    import hashlib
    from urllib.parse import quote
    from trustfork.runtime.dynamic.common import repo_root
    source=repo_root()/task.case['source_task_path']/'environment/mock-api/data'
    pages=sorted(source.rglob('*.html'));assert pages
    for index,page in enumerate(pages):
        url='http://127.0.0.1:8000/download/'+quote(page.relative_to(source).as_posix())
        script='import urllib.request,hashlib; d=urllib.request.urlopen('+repr(url)+',timeout=5).read(); print(hashlib.sha256(d).hexdigest())'
        response=task.exec_work_operation('process.argv',{'argv':['python','-c',script]},'original-page-'+str(index))
        assert response['exitCode']==0
        assert base64.b64decode(response['output']).decode().strip()==hashlib.sha256(page.read_bytes()).hexdigest()
    # Match the unchanged original docker-compose.yaml launch command.
    servers=[row for row in task.baseline_processes if row['command'].split()[:2]==['python3','/opt/mock-api/app.py']]
    assert len(servers)==1, task.baseline_processes
    task.docker('exec',task.container,'python','-c','import os,signal; os.kill('+str(servers[0]['pid'])+',signal.SIGKILL)')
    with pytest.raises(DynamicError,match='service_not_ready'):
        task.start_services()


def test_component_stage_barrier_stops_old_background_on_real_backend(task,tmp_path):
    from trustfork.runtime.dynamic.events import EventLedger
    from trustfork.runtime.dynamic.lifecycle import Lifecycle
    # An explicit component fixture, not an invented stage in the p001 card.
    ledger=EventLedger(tmp_path/'barrier-events.jsonl','component-fixture','p001')
    lifecycle=Lifecycle(ledger);lifecycle.state='RUNNING'
    task.exec_work_operation('process.bash',{'command':'(sleep 2; echo escaped > /workspace/old-epoch.txt) >/tmp/epoch-bg.log 2>&1 &'},'epoch-background')
    lifecycle.close_stage(task,next_stage={'id':'component_fixture_next_epoch','new_session':False},
        deadline=time.monotonic()+30,drain=lambda epoch:None,reset=lambda epoch:None,migrate=lambda old,new:None)
    assert lifecycle.epoch==1
    time.sleep(2.2)
    assert not task.exec_work_operation('fs.exists',{'path':'/workspace/old-epoch.txt'},'old-epoch-check')['exists']
    assert task.start_services()['status']=='running'


def test_audit_real_stream_exit_timeout_and_cancel_preserve_raw_results(tmp_path):
    from trustfork.runtime.dynamic.events import EventLedger,EvidenceStore
    ledger=EventLedger(tmp_path/'receipt-events','receipt-fixture','p001')
    environment=DockerEnvironment(tmp_path/'receipts',branch_id='receipt-fixture',ledger=ledger)
    scope={'actor_id':'C','stage_id':'ask','stage_epoch':0,'request_id':'synthetic-request','invocation_id':None}
    try:
        environment.prepare(load_case('p001'))
        failed=list(environment.stream_work_operation({'argv':['python','-c','import sys; sys.exit(2)']},'exit-2',scope=scope))
        timeout=list(environment.stream_work_operation({'argv':['python','-c','import time; time.sleep(5)'],'timeout':0.1},'timeout',scope=scope))
        environment.cancelled_operations.add('cancel-before-start')
        cancelled=list(environment.stream_work_operation({'argv':['python','-c','raise Exception("must not run")']},'cancel-before-start',scope=scope))
        assert failed[-1]['result']['exitCode']==2
        assert timeout[-1]['result']['timed_out'] is True
        assert cancelled[-1]['result']['cancelled_before_start'] is True
        finished=[e for e in ledger.rows if e['event_type']=='tool_operation_finished']
        assert [e['payload']['receipt']['operation_status'] for e in finished]==['failed','failed','cancelled']
        for event,frames in zip(finished,[failed,timeout,cancelled]):
            raw=EvidenceStore(environment.root/'operation-evidence','receipt-fixture').get(
                event['payload']['receipt']['raw_result_ref'],branch_id='receipt-fixture')
            assert raw['frames']==frames
            assert event['payload']['receipt']['effect_status']=='not_assessed'
    finally:environment.close()
