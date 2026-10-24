"""Explicit pinned dependency setup. Normal runs never download dependencies."""
from __future__ import annotations
import argparse
import hashlib
import io
import os
import tarfile
import urllib.request
from pathlib import Path
from .common import DynamicError, config_dir, read_json


def fd_lock():
    return read_json(config_dir()/'runtime-dependencies.lock.json')['fd']


def fd_binary():
    lock=fd_lock()
    target=Path(os.environ.get('TRUSTFORK_FD_BIN',str(Path.home()/'.local/share/trustfork-env'/('fd-'+lock['version'])/'fd')))
    if not target.is_file():raise DynamicError('missing_locked_fd','Run the explicit pinned dependency setup before starting trials')
    if hashlib.sha256(target.read_bytes()).hexdigest()!=lock['binary_sha256']:
        raise DynamicError('fd_hash_drift','Pinned fd binary changed')
    return target


def install_fd():
    lock=fd_lock()
    target=Path.home()/'.local/share/trustfork-env'/('fd-'+lock['version'])/'fd'
    if target.exists():return fd_binary()
    with urllib.request.urlopen(lock['url'],timeout=90) as response:data=response.read()
    if hashlib.sha256(data).hexdigest()!=lock['archive_sha256']:raise DynamicError('fd_archive_hash_drift','Fixed-release bytes changed')
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:binary=archive.extractfile(lock['archive_member']).read()
    if hashlib.sha256(binary).hexdigest()!=lock['binary_sha256']:raise DynamicError('fd_binary_hash_drift','Unexpected binary')
    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(binary);target.chmod(0o755)
    return fd_binary()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--install-fd',action='store_true')
    args=parser.parse_args()
    binary=install_fd() if args.install_fd else fd_binary()
    print({'status':'verified','dependency':'fd','version':fd_lock()['version'],'sha256':fd_lock()['binary_sha256']})
