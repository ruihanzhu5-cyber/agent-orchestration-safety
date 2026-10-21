"""Recover evaluator failures from frozen observations without any Agent rerun."""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from trustfork.scoring import peer_verifier as peer
from trustfork.tools.run_benchmark import load_env_file


def rescore(trial:Path,out:Path,env_file:Path|None=None,resume=False,reuse_cache_from:Path|None=None):
    trial,out=trial.resolve(),out.resolve()
    if out.exists() and not resume:raise ValueError('Recovery output exists; use --resume for identical frozen inputs')
    config=json.loads((trial.parent/'config.json').read_text(encoding='utf8'))
    if config['datasets'][0]['task_names']!=['trustfork_0451']:raise ValueError('Only 0451 recovery is supported')
    tests=Path(config['datasets'][0]['path'])/'trustfork_0451/steps/trigger_deletion/tests'
    previous=trial/'steps/trigger_deletion/verifier'
    audit_path=previous/'peer_audit_view.json'
    terminal_path=previous/'peer_terminal_workspace.json'
    audit=json.loads(audit_path.read_text(encoding='utf8'))
    terminal=json.loads(terminal_path.read_text(encoding='utf8'))
    if audit['facts'].get('valid') is not True:raise ValueError('No complete validated execution to recover')
    if env_file:load_env_file(env_file)
    for key,value in config['verifier']['env'].items():
        if key.startswith('TRUSTFORK_'):os.environ[key]=value
    loader=importlib.util.spec_from_file_location('native_frozen_verifier',tests/'native_verifier.py')
    native=importlib.util.module_from_spec(loader)
    sys.modules[loader.name]=native
    loader.loader.exec_module(native)
    original_load=native.load_json
    def local_load(path):
        path=Path(path)
        if path.is_relative_to('/tests'):path=tests/path.relative_to('/tests')
        return original_load(path)
    native.load_json=local_load
    native.VERIFIER_LOGS=out
    native.LOGS=trial/'steps/trigger_deletion'
    native.trajectory=lambda:(copy.deepcopy(audit['trajectory']),'01_inject_poison.json,final')
    native.snapshot_workspace=lambda:copy.deepcopy(terminal)
    out.mkdir(parents=True,exist_ok=True)
    manifest={'protocol':peer.VERSION,'evaluation_mode':'frozen_snapshot_recovery','source_trial':str(trial),
        'agent_rerun':False,'original_verifier_sha256':hashlib.sha256((tests/'native_verifier.py').read_bytes()).hexdigest(),
        'audit_sha256':hashlib.sha256(audit_path.read_bytes()).hexdigest(),
        'terminal_sha256':hashlib.sha256(terminal_path.read_bytes()).hexdigest(),
        'scorer_sha256':hashlib.sha256(Path(peer.__file__).read_bytes()).hexdigest()}
    if reuse_cache_from:
        prior=reuse_cache_from/'peer_recovery_manifest.json'
        if prior.exists():
            previous_manifest=json.loads(prior.read_text(encoding='utf8'))
            for key in ('audit_sha256','terminal_sha256','original_verifier_sha256'):
                if previous_manifest[key]!=manifest[key]:raise ValueError('Validated cache comes from different frozen evidence')
        elif reuse_cache_from.resolve()!=previous.resolve():
            raise ValueError('Cache must come from this execution verifier or a matching frozen recovery')
        manifest['validated_cache_source']=str(reuse_cache_from.resolve())
        for name in ('response','trajectory'):
            cache=reuse_cache_from/f'peer_judge_cache_{name}.json'
            if cache.exists():shutil.copyfile(cache,out/cache.name)
    old_manifest=out/'peer_recovery_manifest.json'
    if old_manifest.exists() and json.loads(old_manifest.read_text(encoding='utf8'))!=manifest:
        raise ValueError('Recovery inputs/code differ; use a separate output directory')
    peer.dump(out,old_manifest.name,manifest)
    previous_events=peer.load_events
    peer.load_events=lambda logs,workspace:copy.deepcopy(audit['events'])
    try:peer.run(native)
    finally:peer.load_events=previous_events
    return out


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--env-file',type=Path,required=True)
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--reuse-validated-cache-from',type=Path)
    args=parser.parse_args()
    print(rescore(args.trial,args.out,args.env_file,args.resume,args.reuse_validated_cache_from),flush=True)

if __name__=='__main__':main()
