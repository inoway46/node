"""Regression checks for the remaining-platform validation harness."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('harness', Path(__file__).with_name('run.py'))
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


class ValidationTests(unittest.TestCase):
    def test_bytecode_does_not_change_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'testcfg.py').write_text('value = 1\n')
            before = {'sea': harness.manifest(root)}
            subprocess.run([sys.executable, '-B', '-c', 'import testcfg'], cwd=root, check=True)
            self.assertEqual(harness.manifest_changes(before, {'sea': harness.manifest(root)}), {})
            (root / 'testcfg.py').write_text('value = 2\n')
            (root / 'new.txt').touch()
            delta = harness.manifest_changes(before, {'sea': harness.manifest(root)})
            self.assertEqual(delta['sea']['modified'], ['testcfg.py'])
            self.assertEqual(delta['sea']['added'], ['new.txt'])

    def test_linux_shared_runtime_path(self):
        with patch.object(harness.sys, 'platform', 'linux'), patch.dict(os.environ, {'LD_LIBRARY_PATH': '/existing'}):
            env = harness.runtime_env(Path('/work'), {'bundled': False})
            self.assertEqual(env['LD_LIBRARY_PATH'], '/work/lief-install/lib:/existing')

    def test_smoke_failure_preserves_later_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            node = work / 'node'
            (node / 'test/sea').mkdir(parents=True)
            (node / 'test/sea/sea.status').write_text('prefix sea\n')
            runner = harness.Runner(work / 'results')
            calls = []

            def run(label, command, cwd, **kwargs):
                calls.append(label)
                if label == 'node-runtime':
                    return 0, json.dumps({'versions': {'lief': '1.0.0'}, 'arch': 'x64',
                                         'config': {'node_shared_lief': False, 'node_use_lief': True,
                                                    'single_executable_application': True}})
                if label == 'sea-suite':
                    self.assertIn('-B', command)
                    (runner.results / 'sea-tests.tap').write_text('ok 1 sea/test-example\n')
                return 0, ''

            data = {'bundled': True, 'version': '1.0.0', 'arch': 'x64',
                    'node_revision': 'test', 'variant': 'bundled-1.0.0', 'platform': 'darwin'}
            with patch.object(harness, 'state', return_value=(work, node, data, runner)), \
                    patch.object(runner, 'run', side_effect=run), \
                    patch.object(harness, 'inspect_dependencies'), \
                    patch.object(harness, 'smoke', side_effect=RuntimeError('execution failed')):
                args = type('Args', (), {'execute_sea': True})()
                with self.assertRaises(RuntimeError):
                    harness.test(args)
            result = json.loads((runner.results / 'result.json').read_text())
            self.assertEqual(result['failed_tests'], ['sea-smoke'])
            self.assertEqual(result['status'], 'failed')
            self.assertIn('test-single-executable-application-assets', calls)
            self.assertIn('sea-suite', calls)


if __name__ == '__main__':
    unittest.main()
