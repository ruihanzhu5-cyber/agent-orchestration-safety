"""Prepare/run only 0451 Direct, Control and Chain with external local credentials."""
from __future__ import annotations
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from trustfork.tools import generate_jobs as g, run_benchmark as runner
from trustfork.scoring.aggregate_peer import aggregate


def write(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8')


def task_assets():
    task=ROOT/'trustfork/tasks/chain/trustfork_0451'
    return {p.relative_to(task).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(task.rglob('*')) if p.is_file() and 'tests' not in p.relative_to(task).parts}


def reuse_reference_transport(config, reference):
    """Reuse reviewed network/model-limit compatibility fields, never old orchestration."""
    if not reference:
        return
    old=json.loads(reference.read_text(encoding='utf8'))
    current=config['agents'][0]
    previous=old['agents'][0]
    if current['model_name'] != previous['model_name']:
        raise ValueError('Transport reference backbone differs')
    if old['environment'].get('extra_docker_compose'):
        config['environment']['extra_docker_compose']=old['environment']['extra_docker_compose']
    providers=current['kwargs']['opencode_config']['provider']
    old_providers=previous['kwargs']['opencode_config']['provider']
    if set(providers)!=set(old_providers): raise ValueError('Transport reference provider set differs')
    for name,provider in providers.items():
        prior=old_providers[name]
        if provider['npm']!=prior['npm'] or provider['options']!=prior['options']:
            raise ValueError('Transport reference changes endpoint/credential binding')
        for model,settings in provider['models'].items():
            limit=prior['models'].get(model,{}).get('limit')
            if limit: settings['limit']=copy.deepcopy(limit)


def historical_records(root, backbone):
    records=[]
    if root is None: return records
    for condition in ('truthful','swap'):
        job=root/f'{backbone}__opencode__trustfork_0451__{condition}'
        candidates=list(job.glob('*/steps/trigger_deletion/verifier/annotations.json'))
        if len(candidates)!=1:
            records.append({'condition':condition,'status':'unknown','reason':'No unique retained historical annotation'})
            continue
        path=candidates[0]
        data=json.loads(path.read_text(encoding='utf8'))
        reward=path.with_name('reward.json')
        records.append({'condition':condition,'status':'historical_reference',
            'task_id':data['task_id'],'trial_id':path.parents[3].name,
            'breadth_compliant':data.get('breadth_validation',{}).get('compliant'),
            'eight_scores':data['benchmark_scores']['report_score_0_100'],
            'annotation_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'reward_sha256':hashlib.sha256(reward.read_bytes()).hexdigest() if reward.exists() else None,
            'path':str(path)})
    return records


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--systems-config',type=Path,required=True)
    parser.add_argument('--pools-config',type=Path,required=True)
    parser.add_argument('--env-file',type=Path,required=True)
    parser.add_argument('--system',default='gpt-4o@opencode')
    parser.add_argument('--out',type=Path)
    parser.add_argument('--historical-reference',type=Path)
    parser.add_argument('--transport-reference',type=Path,help='Existing successful Harbor config: reuse only compose and model limits')
    parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--resume',action='store_true',help='Continue this output directory; never resample valid trials')
    parser.add_argument('--modes',nargs='+',choices=['direct','peer_control','peer_chain'],default=['direct','peer_control','peer_chain'])
    args=parser.parse_args()
    if os.name=='nt': parser.error('Execute with the Linux Python environment in WSL (Docker allowlist support).')
    out=(args.out or ROOT/'build/peer-pilot'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')).resolve()
    if out.exists() and not args.resume: parser.error('Output exists: use --resume to continue, or a fresh directory.')
    import fcntl
    out.mkdir(parents=True, exist_ok=True)
    lock=(out/'.pilot.lock').open('w')
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error('This pilot directory is already running; do not start a concurrent resume.')
    backbone,cli=args.system.split('@',1)
    if cli!='opencode': parser.error('Only OpenCode is supported.')
    import yaml
    systems=yaml.safe_load(args.systems_config.read_text(encoding='utf8'))
    if backbone not in systems['evaluation_scope'].get(cli,[]): parser.error('System outside evaluation scope')
    orchestrator=systems['backbones'][backbone]
    task=ROOT/'trustfork/tasks/chain/trustfork_0451'
    spec=g.load_json(task/'tests/task_spec.private.json')
    pools=g.load_json(args.pools_config)['templates']
    pool=g.resolve_pool(pools[spec['pool_template_id']],orchestrator,systems['backbones'],systems['model_registry'],spec)
    display=g.render_display(spec,pool,orchestrator)
    goal=g.load_json(g.GOALS_CONFIG)[spec['actor_goal_id']]['focal_prompt']
    metadata=g.load_json(task/'tests/task_metadata.json')
    goals={slot:None for slot in pool}
    goals[spec['focal_actor_slot']]=goal.format(attack_goal=metadata.get('attack_goal',''))
    conditions=[]
    signature=None
    for mode in args.modes:
        system=f'{backbone}__{cli}__peer-{mode}'
        config=g.job_config(system,cli,orchestrator,systems['providers'],task,spec,pool,display,goals,peer_mode=mode)
        reuse_reference_transport(config,args.transport_reference)
        config['jobs_dir']=str(out/'jobs')
        config['datasets'][0]['path']=str(ROOT/config['datasets'][0]['path'])
        # Static task allowlists are extended only with configured provider hosts,
        # by the native Harbor adapter; no network-policy bypass.
        config['agents'][0]['env']['LITELLM_LOCAL_MODEL_COST_MAP']='True'
        fixed={'task_id':spec['task_id'],'identity':display,'goal':goals,'pool':pool,
               'agent_config':config['agents'][0]['kwargs']['opencode_config'],
               'assets':task_assets(),'budget':config['timeout_multiplier'],
               'transport':config['environment'],
               'protocol':'trustfork-peer-v0.3','native_verifier_sha256':hashlib.sha256((task/'steps/trigger_deletion/tests/verifier.py').read_bytes()).hexdigest()}
        signature=hashlib.sha256(json.dumps(fixed,sort_keys=True).encode()).hexdigest()
        path=out/'configs'/f'{mode}.json'
        # Resume must use identical generated code and conditions, not silently replace an ongoing experiment.
        if path.exists() and json.loads(path.read_text())!=config: raise ValueError('Resume config differs from the prepared run')
        write(path,config)
        conditions.append({'mode':mode,'config':str(path),'job_name':config['job_name'],
                           'job_dir':str(out/'jobs'/config['job_name']),'match_signature':signature})
    manifest={'protocol':'trustfork-peer-v0.3','official_base':'49490514f5187ba4e04b31929f2f4470e0db7def',
        'task_id':spec['task_id'],'condition':spec['identity_display_id'],'goal':spec['actor_goal_id'],
        'breadth':spec['breadth_regime'],'source_slot':spec['focal_actor_slot'],'recipient_slot':'B',
        'actual_models':{s:v['api_model'] for s,v in pool.items()},'display':display,'conditions':conditions,
        'historical_reference':str(args.historical_reference.resolve()) if args.historical_reference else None,
        'historical_records':historical_records(args.historical_reference,backbone),
        'transport_reference':str(args.transport_reference.resolve()) if args.transport_reference else None,
        'comparability':{'historical':'Yesterday is observational reference, not a new Direct condition.',
           'intake_calls':'Direct/Control 1 vs Chain 2; not token/call matched',
           'workspace':'Original shared workspace; source writes may reach recipient without message',
           'budget':'Same original timeouts, multiplier 1; two fresh Main sessions',
           'identity':'Fixed M1 displayed identities; no topology/identity causal interaction claim from this case'}}
    write(out/'peer_run_manifest.json',manifest)
    print(f'Prepared 0451 only: {out}',flush=True)
    if args.prepare_only: return
    runner.load_env_file(args.env_file)
    required={systems['providers'][v['provider']]['api_key_env'] for v in [orchestrator,*pool.values()]}|{'DEEPSEEK_API_KEY'}
    if any(not os.environ.get(k) for k in required): raise ValueError('Missing required API environment names: '+', '.join(k for k in required if not os.environ.get(k)))
    runner.HARBOR_BIN=str(Path(sys.executable).parent/'harbor')
    if not Path(runner.HARBOR_BIN).exists(): raise ValueError('Harbor is absent beside this Python')
    os.environ['LITELLM_LOCAL_MODEL_COST_MAP']='True'
    subprocess.run([sys.executable,str(ROOT/'trustfork/tools/ensure_base_image.py')],cwd=ROOT,check=True)
    runner.ATTEMPTS_ROOT=out/'attempts'
    runner.MAX_ATTEMPTS=1  # preserve one actual execution; recover grading on frozen observations
    ledger_path=out/'run_ledger.json'
    ledger=runner.load_ledger(ledger_path)
    worker=runner.TaskRunner(ledger,ledger_path)
    for item in conditions:
        if ledger['jobs'].get(item['job_name'],{}).get('status')=='exhausted':
            print(f"Skipping exhausted {item['mode']}; inspect infrastructure logs",flush=True)
            continue
        _,result=worker.run(Path(item['config']),item['job_name'],False)
        auxiliaries=list(Path(item['job_dir']).glob('*/steps/trigger_deletion/verifier/peer_metrics.json'))
        auxiliary_valid=(len(auxiliaries)==1 and json.loads(auxiliaries[0].read_text(encoding='utf8')).get('status')=='valid')
        if result['status']!='valid' or not auxiliary_valid:
            captures=list(Path(item['job_dir']).glob('*/steps/trigger_deletion/verifier/peer_audit_view.json'))
            if len(captures)==1:
                from trustfork.scoring.rescore_peer import rescore
                trial=captures[0].parents[3]
                evaluation=out/'score-recovery'/item['mode']
                try:
                    rescore(trial,evaluation,resume=evaluation.exists(),reuse_cache_from=captures[0].parent)
                    recovered=json.loads((evaluation/'annotations.json').read_text(encoding='utf8'))
                    if not recovered.get('breadth_validation',{}).get('compliant'):
                        raise ValueError('Recovered native breadth gate failed')
                    result['status']='valid_recovered'
                    result['evaluation_path']=str(evaluation)
                    item['evaluation_path']=str(evaluation)
                except Exception as exc:
                    result['recovery_error']=str(exc)
                    result['status']='grading_failed'
                worker.persist(item['job_name'],result)
                write(out/'peer_run_manifest.json',manifest)
        print(f"{item['mode']}: {result['status']}",flush=True)
    aggregate(out)
    print(f'Report: {out / "peer_summary.md"}',flush=True)


if __name__=='__main__': main()
