"""Offline checks without credentials, model calls, or a task launch."""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

from trustfork.runtime.dynamic.common import BASE_COMMIT, BASE_IMAGE, BASE_IMAGE_ID, repo_root, read_json, write_json
from trustfork.runtime.dynamic.schema import validate_bindings
from trustfork.runtime.dynamic.dependencies import fd_binary,fd_lock
from trustfork.runtime.dynamic.common import DynamicError,file_hash


def collect_checks():
    root = repo_root()
    checks = {}
    def command(name, argv):
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        checks[name] = {'status': 'pass' if result.returncode == 0 else 'blocked', 'exit_code': result.returncode}
        return result
    result = command('fixed_base', ['git', '-C', str(root), 'merge-base', 'HEAD', BASE_COMMIT])
    checks['fixed_base']['status'] = 'pass' if result.stdout.strip() == BASE_COMMIT else 'blocked'
    result=command('docker_daemon', ['/usr/bin/docker','--host','unix:///var/run/docker.sock','info', '--format', '{{.OSType}}'])
    checks['docker_daemon']['status']='pass' if result.returncode==0 and result.stdout.strip()=='linux' else 'blocked'
    result = command('audited_image', ['/usr/bin/docker', 'image', 'inspect', BASE_IMAGE, '--format', '{{.Id}}'])
    checks['audited_image']['status'] = 'pass' if result.stdout.strip() == BASE_IMAGE_ID else 'blocked'
    bindings = validate_bindings(read_json(root / 'trustfork/config/dynamic/model_bindings.example.json'), formal=False)
    checks['offline_model_configuration'] = {'status': 'pass', **bindings, 'real_model_requests': 0, 'real_judge_requests': 0}
    catalog = read_json(root / 'trustfork/config/dynamic/cases.json')
    checks['case_mapping'] = {'status': 'pass' if len(catalog) == 30 and not any(c['errors'] for c in catalog.values()) else 'blocked', 'mapped': len(catalog)}
    checks['node_project'] = {'status': 'pass' if (root / 'trustfork/runtime/dynamic/node_modules/@earendil-works/pi-coding-agent').exists() else 'not_ready'}
    runtime=root/'trustfork/runtime/dynamic';lock=read_json(runtime/'pi-patch.lock.json');package=runtime/'node_modules/@earendil-works/pi-coding-agent'
    if package.exists():
        valid=read_json(package/'package.json')['version']=='0.84.1' and all(file_hash(package/item['path'])==item['patched_sha256'] for item in lock['files'])
        checks['patched_sdk_hashes']={'status':'pass' if valid else 'blocked','files':len(lock['files']),'pi_version':'0.84.1'}
    try:fd_binary()
    except DynamicError as error:checks['native_fd']={'status':'blocked','reason':error.code}
    else:checks['native_fd']={'status':'pass','version':fd_lock()['version'],'sha256':fd_lock()['binary_sha256']}
    return {'mode': 'offline', 'checks': checks, 'real_model_requests': 0, 'real_judge_requests': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['offline'], required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = collect_checks()
    write_json(args.out, result)
    print(json.dumps(result, indent=2))
    if any(c['status'] == 'blocked' for c in result['checks'].values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
