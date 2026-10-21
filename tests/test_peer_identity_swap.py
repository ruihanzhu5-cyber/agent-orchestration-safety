"""No-API tests for label-only intervention and preservation of truthful runs."""
import json
from pathlib import Path
import tempfile
import unittest

from trustfork.tools.run_peer_identity_swap import prepare, config_without_identity


class IdentitySwapTests(unittest.TestCase):
    def fixture(self, root):
        reference = root / 'truthful'
        reference.mkdir()
        task = root / 'frozen-tasks/trustfork_0451'
        task.mkdir(parents=True)
        specs = {'task_id': 'trustfork_0451', 'identity_display_id': 'M1', 'condition': 'M1',
                 'identity_swap_pair': None, 'actor_goal_id': 'G1', 'focal_actor_slot': 'D',
                 'actors': {s: {'displayed_identity': s, 'actor_goal_id': 'G1' if s == 'D' else 'user_aligned'} for s in 'ABCD'}}
        files = {'tests/task_spec.private.json': json.dumps(specs),
                 'steps/inject_poison/tests/task_spec.private.json': json.dumps(specs),
                 'tests/native_verifier.py': '# frozen original scorer\n',
                 'tests/peer_verifier.py': '# frozen Peer scorer\n',
                 'instruction.md': 'LEGITIMATE USER TASK', 'environment/workspace/trash.txt': ''}
        for name, text in files.items():
            path = task / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf8')
        display = {'A': 'DeepSeek', 'B': 'GPT', 'C': 'DeepSeek', 'D': 'DeepSeek'}
        manifest = {'task_id': 'trustfork_0451', 'protocol': 'trustfork-peer-v0.3', 'condition': 'M1',
                    'source_slot': 'D', 'recipient_slot': 'B', 'display': display, 'conditions': [],
                    'comparability': {'identity': 'truthful'}}
        for mode in ('direct', 'peer_control', 'peer_chain'):
            config = {'job_name': 'test-' + mode, 'jobs_dir': str(reference / 'jobs'),
                      'datasets': [{'path': str(task.parent)}], 'timeout_multiplier': 1,
                      'agents': [{'model_name': 'provider/gpt', 'kwargs': {
                          'opencode_plugins': {'peer.js': f'FROZEN {mode} RUNTIME'},
                          'opencode_config': {'agent': {f'candidate_{s.lower()}': {
                              'description': f'{display[s]}.', 'model': 'provider/' + ('gpt' if s == 'B' else 'deepseek'),
                              'prompt': 'PRIVATE GOAL' if s == 'D' else 'BENIGN', 'tools': {'task': False}}
                              for s in 'ABCD'}}}}],
                      'verifier': {'env': {'TRUSTFORK_DISPLAYED_IDENTITY_BY_ACTOR': json.dumps(display)}}}
            path = reference / (mode + '.json')
            path.write_text(json.dumps(config), encoding='utf8')
            manifest['conditions'].append({'mode': mode, 'config': str(path), 'job_name': config['job_name'],
                                           'job_dir': str(reference / 'jobs' / config['job_name']), 'match_signature': 'same'})
        (reference / 'peer_run_manifest.json').write_text(json.dumps(manifest), encoding='utf8')
        return reference, task

    def test_only_public_labels_and_evaluator_identity_metadata_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference, source = self.fixture(root)
            before = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            result = prepare(reference, root / 'swap', root)
            self.assertEqual(result['condition'], 'M2')
            self.assertEqual(result['display']['B'], 'DeepSeek')
            self.assertEqual(result['display']['D'], 'GPT')
            self.assertEqual(len(result['conditions']), 3)
            original = json.loads((reference / 'peer_run_manifest.json').read_text())
            for prior, current in zip(original['conditions'], result['conditions']):
                a = json.loads(Path(prior['config']).read_text())
                b = json.loads(Path(current['config']).read_text())
                self.assertEqual(config_without_identity(a), config_without_identity(b))
                self.assertNotEqual(a['job_name'], b['job_name'])
                overlay = Path(b['datasets'][0]['path']) / 'trustfork_0451'
                for path in source.rglob('*'):
                    if not path.is_file():
                        continue
                    target = overlay / path.relative_to(source)
                    if path.name == 'task_spec.private.json':
                        data = json.loads(target.read_text())
                        self.assertEqual(data['identity_swap_pair'], ['B', 'D'])
                        self.assertEqual(data['actor_goal_id'], 'G1')
                        original_spec = json.loads(path.read_text())
                        for slot in ('A', 'C'):
                            self.assertEqual(data['actors'][slot], original_spec['actors'][slot])
                    else:
                        self.assertEqual(path.read_bytes(), target.read_bytes())
            self.assertTrue(all(Path(name).read_bytes() == content for name, content in before.items()))
            self.assertEqual(result, prepare(reference, root / 'swap', root))

    def test_rejects_reference_without_confirmed_truthful_roster(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference, _ = self.fixture(root)
            p = reference / 'direct.json'
            config = json.loads(p.read_text())
            config['agents'][0]['kwargs']['opencode_config']['agent']['candidate_d']['description'] = 'unexpected.'
            p.write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError, 'roster differs'):
                prepare(reference, root / 'swap', root)


if __name__ == '__main__':
    unittest.main()
