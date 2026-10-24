"""These tests run the original Docker task services, without a model provider."""
import base64
import io
import json
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor

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


@pytest.mark.parametrize('case_id', ['p001', 'p024', 'p028'])
def test_source_task_snapshot_restore_after_real_work(tmp_path, case_id):
    first = DockerEnvironment(tmp_path / 'original')
    second = DockerEnvironment(tmp_path / 'restored')
    try:
        first.prepare(load_case(case_id))
        first.exec_work_operation('fs.write', {'path': '/workspace/restore-evidence.txt', 'data': encoded('changed in original task')}, 'change')
        snapshot = first.checkpoint_state(time.monotonic() + 30)
        first.close()
        restored = second.restore(snapshot)
        assert restored['status'] == 'verified_restored' and restored['ram_saved'] is False
        assert base64.b64decode(second.exec_work_operation('fs.read', {'path': '/workspace/restore-evidence.txt'}, 'verify')['data']) == b'changed in original task'
    finally:
        first.close()
        second.close()


def test_freeze_stops_background_mutation_and_uses_readonly_export(task):
    task.exec_work_operation('process.bash', {'command': '(sleep 1; echo late > /workspace/background.txt) >/tmp/bg.log 2>&1 &'}, 'background')
    task.quiesce(time.monotonic() + 30)
    task.freeze()
    before = task.export_state()
    frozen_bytes = open(before['workspace_tar'], 'rb').read()
    time.sleep(1.2)
    assert task.docker('cp', task.container + ':/workspace/.', '-', binary=True).stdout == frozen_bytes
    with pytest.raises(DynamicError, match='environment_not_accepting'):
        task.exec_work_operation('fs.write', {'path': '/workspace/no', 'data': ''}, 'forbidden')
    with tarfile.open(fileobj=io.BytesIO(frozen_bytes)) as archive:
        assert not any(m.name.endswith('background.txt') for m in archive)
