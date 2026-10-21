"""Run the three 0451 label-swap conditions from frozen truthful Peer configs."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from trustfork.tools import run_benchmark as runner
from trustfork.tools.run_peer_pilot import write
from trustfork.scoring.aggregate_peer import aggregate

MODES = ('direct', 'peer_control', 'peer_chain')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def config_without_identity(config):
    """Only these fields may differ within a truthful/swap pair."""
    value = copy.deepcopy(config)
    for key in ('job_name', 'jobs_dir'):
        value.pop(key, None)
    for dataset in value['datasets']:
        dataset.pop('path', None)
    for slot in 'bd':
        value['agents'][0]['kwargs']['opencode_config']['agent'][f'candidate_{slot}'].pop('description')
    value['verifier']['env'].pop('TRUSTFORK_DISPLAYED_IDENTITY_BY_ACTOR')
    return value


def swap_overlay(source: Path, display: dict, root: Path = ROOT):
    """Change evaluator-only identity metadata; preserve every other task byte."""
    files = {p.relative_to(source).as_posix(): p.read_bytes()
             for p in sorted(source.rglob('*')) if p.is_file()}
    changed = []
    for name in files:
        if not name.endswith('tests/task_spec.private.json'):
            continue
        spec = json.loads(files[name])
        if spec['task_id'] != 'trustfork_0451' or spec['identity_display_id'] != 'M1':
            raise ValueError('Expected original 0451/M1 evaluator metadata')
        spec.update(condition='M2', identity_display_id='M2', identity_swap_pair=['B', 'D'])
        # Retain canonical benchmark IDs as source references; this is a runtime
        # identity intervention on 0451, not a newly published benchmark task.
        for slot in ('B', 'D'):
            spec['actors'][slot]['displayed_identity'] = display[slot]
        files[name] = (json.dumps(spec, ensure_ascii=False, indent=2) + '\n').encode()
        changed.append(name)
    if not changed:
        raise ValueError('No evaluator-only task specs found')
    content_hash = hashlib.sha256()
    for name, content in sorted(files.items()):
        content_hash.update(name.encode() + b'\0' + content)
    parent = root / 'build/peer-identity-tasks/swap' / content_hash.hexdigest()[:20]
    target = parent / source.name
    if not target.exists():
        parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix='.preparing-', dir=parent))
        for name, content in files.items():
            path = temporary / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        temporary.rename(target)
    # Validate even a reused cache against the exact intended bytes.
    if {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob('*') if p.is_file()} != files:
        raise ValueError('Identity overlay cache content mismatch')
    return target, changed


def prepare(reference: Path, out: Path, root: Path = ROOT):
    original = json.loads((reference / 'peer_run_manifest.json').read_text(encoding='utf8'))
    if (original['task_id'] != 'trustfork_0451' or original['protocol'] != 'trustfork-peer-v0.3'
            or original['condition'] != 'M1' or original['source_slot'] != 'D'
            or original['recipient_slot'] != 'B'
            or len(original['conditions']) != 3
            or {c['mode'] for c in original['conditions']} != set(MODES)):
        raise ValueError('Reference must be the three truthful 0451/v0.3 conditions')
    display = dict(original['display'])
    display['B'], display['D'] = display['D'], display['B']
    manifest = copy.deepcopy(original)
    manifest.update(condition='M2', source_task_condition='M1', identity_swap_pair=['B', 'D'],
                    display=display, paired_truthful_reference=str(reference), conditions=[])
    manifest['comparability']['identity'] = ('B/D public descriptions swapped; actual models, goals, '
        'runtime, tools, budgets, task instructions and assets frozen from the truthful reference. '
        'Both source and messenger identities change together; one case is exploratory.')
    audits = []
    for item in original['conditions']:
        original_config = json.loads(Path(item['config']).read_text(encoding='utf8'))
        config = copy.deepcopy(original_config)
        roster = config['agents'][0]['kwargs']['opencode_config']['agent']
        expected = {f'candidate_{s.lower()}': f'{label}.' for s, label in original['display'].items()}
        if any(roster[profile]['description'] != label for profile, label in expected.items()):
            raise ValueError('Frozen truthful roster differs from its manifest')
        for slot in ('B', 'D'):
            roster[f'candidate_{slot.lower()}']['description'] = f'{display[slot]}.'
        config['verifier']['env']['TRUSTFORK_DISPLAYED_IDENTITY_BY_ACTOR'] = json.dumps(
            display, ensure_ascii=False, separators=(',', ':'))
        config['job_name'] += '__swap'
        config['jobs_dir'] = str(out / 'jobs')
        source_dataset = Path(original_config['datasets'][0]['path'])
        if not source_dataset.is_absolute():
            source_dataset = root / source_dataset
        task, changed = swap_overlay(source_dataset / 'trustfork_0451', display, root)
        config['datasets'][0]['path'] = str(task.parent)
        before, after = map(config_without_identity, (original_config, config))
        if before != after:
            raise ValueError('A non-identity runtime/config field changed')
        path = out / 'configs' / f"{item['mode']}.json"
        if path.exists() and json.loads(path.read_text(encoding='utf8')) != config:
            raise ValueError('Resume would replace a frozen swap config')
        write(path, config)
        condition = {'mode': item['mode'], 'config': str(path), 'job_name': config['job_name'],
                     'job_dir': str(out / 'jobs' / config['job_name']),
                     'match_signature': digest({'truthful_signature': item['match_signature'], 'display': display})}
        manifest['conditions'].append(condition)
        audits.append({'mode': item['mode'], 'reference_config_sha256': digest(original_config),
                       'swap_config_sha256': digest(config), 'non_identity_config_sha256': digest(before),
                       'non_identity_config_equal': True, 'evaluator_metadata_files_changed': changed,
                       'all_other_task_bytes_equal': True})
    # Preserve evaluation recovery paths if this is an identical resume.
    old_path = out / 'peer_run_manifest.json'
    if old_path.exists():
        old = json.loads(old_path.read_text(encoding='utf8'))
        for condition in manifest['conditions']:
            prior = next(c for c in old['conditions'] if c['mode'] == condition['mode'])
            if prior.get('evaluation_path'):
                condition['evaluation_path'] = prior['evaluation_path']
        if old != manifest:
            raise ValueError('Resume identity manifest differs')
    write(old_path, manifest)
    write(out / 'identity_only_diff.json', {'swap_pair': ['B', 'D'], 'checks': audits,
         'source_benchmark_configuration_ids_retained_as_reference': True,
         'truthful_jobs_will_not_be_executed_by_this_driver': True})
    return manifest


def wait_for_reference(reference: Path, out: Path, timeout=10800):
    """Queue after the existing controller, without invoking any truthful job."""
    previous = None
    started = time.monotonic()
    while True:
        ledger_path = reference / 'run_ledger.json'
        ledger = json.loads(ledger_path.read_text(encoding='utf8')) if ledger_path.exists() else {'jobs': {}}
        states = {name: value.get('status') for name, value in ledger['jobs'].items()}
        write(out / 'queue_state.json', {'state': 'waiting_for_truthful_queue', 'reference_states': states})
        if states != previous:
            print(f'Waiting for existing truthful queue: {states}', flush=True)
            previous = states
        if len(states) == 3 and all(s not in ('running', None) for s in states.values()) and (reference / 'peer_summary.json').exists():
            return
        if time.monotonic() - started > timeout:
            raise TimeoutError('Reference queue did not finish; no truthful job was rerun')
        time.sleep(5)


def paired_report(reference: Path, out: Path):
    reports = [('truthful', json.loads((reference / 'peer_summary.json').read_text(encoding='utf8'))),
               ('swap', aggregate(out))]
    rows = []
    metrics = ('RTF', 'RSR', 'IAS', 'SAF', 'VF', 'EI', 'TH', 'TUL')
    for identity, report in reports:
        directory = reference if identity == 'truthful' else out
        manifest = json.loads((directory / 'peer_run_manifest.json').read_text(encoding='utf8'))
        for row in report['rows']:
            item = next(c for c in manifest['conditions'] if c['mode'] == row['mode'])
            annotations = ([Path(item['evaluation_path']) / 'annotations.json'] if item.get('evaluation_path') else
                           list(Path(item['job_dir']).glob('*/steps/trigger_deletion/verifier/annotations.json')))
            scores = {}
            if len(annotations) == 1 and annotations[0].exists():
                native = json.loads(annotations[0].read_text(encoding='utf8'))
                scores = native.get('benchmark_scores', {}).get('report_score_0_100', {})
            rows.append({'identity': identity, **row, 'eight_scores': scores})
    write(out / 'identity_comparison.json', {'task_id': 'trustfork_0451', 'rows': rows,
        'truthful_reference': str(reference), 'scope': 'One execution per cell; descriptive comparison only.'})
    lines = ['# 0451 identity × relay comparison', '',
             '| identity | mode | ' + ' | '.join(metrics) + ' | valid |',
             '|---|---|' + '---:|' * len(metrics) + '---|']
    for row in rows:
        lines.append('| ' + ' | '.join([row['identity'], row['mode'],
                     *(str(row['eight_scores'].get(k, 'unknown')) for k in metrics), str(row['valid'])]) + ' |')
    lines += ['', 'One execution per cell. Scores are 0–100, higher means more severe failure.',
              'See each peer_summary.json for NA/unknown states and evidence; no population or causal claim.',
              'B and D labels change together. Runtime model bindings stay fixed.']
    (out / 'identity_comparison.md').write_text('\n'.join(lines) + '\n', encoding='utf8')


def execute(manifest, reference, out, env_file):
    wait_for_reference(reference, out)
    runner.load_env_file(env_file)
    runner.HARBOR_BIN = str(Path(sys.executable).parent / 'harbor')
    if not Path(runner.HARBOR_BIN).exists():
        raise ValueError('Harbor is absent beside this Python')
    os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'
    subprocess.run([sys.executable, str(ROOT / 'trustfork/tools/ensure_base_image.py')], cwd=ROOT, check=True)
    runner.ATTEMPTS_ROOT = out / 'attempts'
    runner.MAX_ATTEMPTS = 1
    ledger_path = out / 'run_ledger.json'
    worker = runner.TaskRunner(runner.load_ledger(ledger_path), ledger_path)
    for item in manifest['conditions']:
        if item.get('evaluation_path') and (Path(item['evaluation_path']) / 'peer_metrics.json').exists():
            recovered = json.loads((Path(item['evaluation_path']) / 'peer_metrics.json').read_text(encoding='utf8'))
            if recovered.get('status') == 'valid':
                print(f"Keeping recovered swap {item['mode']}", flush=True)
                continue
        write(out / 'queue_state.json', {'state': 'running_swap', 'mode': item['mode']})
        _, result = worker.run(Path(item['config']), item['job_name'], False)
        metrics = list(Path(item['job_dir']).glob('*/steps/trigger_deletion/verifier/peer_metrics.json'))
        auxiliary_valid = len(metrics) == 1 and json.loads(metrics[0].read_text(encoding='utf8')).get('status') == 'valid'
        if result['status'] != 'valid' or not auxiliary_valid:
            captures = list(Path(item['job_dir']).glob('*/steps/trigger_deletion/verifier/peer_audit_view.json'))
            if len(captures) == 1:
                from trustfork.scoring.rescore_peer import rescore
                evaluation = out / 'score-recovery' / item['mode']
                try:
                    rescore(captures[0].parents[3], evaluation, resume=evaluation.exists(), reuse_cache_from=captures[0].parent)
                    recovered = json.loads((evaluation / 'annotations.json').read_text(encoding='utf8'))
                    if not recovered.get('breadth_validation', {}).get('compliant'):
                        raise ValueError('Recovered breadth gate failed')
                    result.update(status='valid_recovered', evaluation_path=str(evaluation))
                    item['evaluation_path'] = str(evaluation)
                except Exception as exc:
                    result.update(status='grading_failed', recovery_error=str(exc))
                worker.persist(item['job_name'], result)
                write(out / 'peer_run_manifest.json', manifest)
        print(f"swap {item['mode']}: {result['status']}", flush=True)
        paired_report(reference, out)
    paired_report(reference, out)
    write(out / 'queue_state.json', {'state': 'finished'})
    print(f"Comparison: {out / 'identity_comparison.md'}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    if os.name == 'nt':
        parser.error('Use the existing Linux/WSL Python environment')
    reference, out = args.reference.resolve(), args.out.resolve()
    if reference == out or reference in out.parents or out in reference.parents:
        parser.error('Swap output must be independent of the truthful reference')
    if out.exists() and not args.resume:
        parser.error('Output exists; choose a fresh directory or --resume')
    import fcntl
    out.mkdir(parents=True, exist_ok=True)
    lock = (out / '.pilot.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error('This swap directory already has a controller')
    manifest = prepare(reference, out)
    print(f'Prepared swap B/D only: {out}', flush=True)
    if not args.prepare_only:
        execute(manifest, reference, out, args.env_file)


if __name__ == '__main__':
    main()
