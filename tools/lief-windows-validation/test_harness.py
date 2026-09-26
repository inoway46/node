import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace


helper_path = Path(__file__).with_name('run.py')
spec = importlib.util.spec_from_file_location('lief_windows_validation', helper_path)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class ValidationChecks(unittest.TestCase):
    def test_smoke_payload_preserves_lf_under_windows_text_translation(self):
        original_write_text = Path.write_text

        def windows_write_text(path, data, *args, **kwargs):
            kwargs.setdefault('newline', '\r\n')
            return original_write_text(path, data, *args, **kwargs)

        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.object(Path, 'write_text', windows_write_text):
                directory, _ = helper.prepare_smoke(Path(temporary), {'version': '1.0.0'})
            self.assertEqual((directory / 'payload.txt').read_bytes(), 'LIEF SEA asset 😊\n'.encode())
            self.assertIn("'LIEF SEA asset 😊\\n'", (directory / 'main.js').read_text(encoding='utf-8'))

    def test_shared_build_host_tools_receive_dll_path_before_build_completes(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            node = work / 'node'
            output = node / 'out/Release'
            output.mkdir(parents=True)
            library = work / 'lief-install/lib'
            library.mkdir(parents=True)
            (library / 'LIEF.dll').write_bytes(b'fixture DLL')
            runner = mock.Mock(results=work / 'results')

            def build(label, command, cwd, *, env):
                self.assertEqual(label, 'node-build')
                self.assertEqual(env['PATH'].split(os.pathsep)[0], str(library))
                self.assertFalse((output / 'LIEF.dll').exists())
                inherited = subprocess.check_output([sys.executable, '-c',
                    'import os; print(os.environ["PATH"].split(os.pathsep)[0])'], env=env, text=True).strip()
                self.assertEqual(inherited, str(library))
                (output / 'node.exe').write_bytes(b'fixture executable')

            runner.run.side_effect = build
            data = {'bundled': False}
            with mock.patch.object(helper, 'state', return_value=(work, node, data, runner)), \
                    mock.patch.object(helper.sys, 'platform', 'win32'):
                helper.build_node(SimpleNamespace(jobs=4))
            self.assertEqual((output / 'LIEF.dll').read_bytes(), b'fixture DLL')

    def test_debug_build_selects_existing_project_build_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            node = work / 'node'
            project = node / 'deps/LIEF/liblief.vcxproj'
            project.parent.mkdir(parents=True)
            project.write_text('<Project DefaultTargets="Build"/>', encoding='utf-8')
            runner = mock.Mock(results=work / 'results')

            def build(label, command, cwd):
                self.assertEqual(command[:3], ['msbuild', project, '/t:Build'])
                self.assertIn('/p:Configuration=Debug', command)
                archive = node / 'out/Debug/lib/liblief.lib'
                archive.parent.mkdir(parents=True)
                archive.write_bytes(b'fixture archive')

            runner.run.side_effect = build
            with mock.patch.object(helper, 'state', return_value=(work, node, {'bundled': True}, runner)), \
                    mock.patch.object(helper.sys, 'platform', 'win32'):
                helper.debug_lief(SimpleNamespace(jobs=4))
            self.assertTrue((runner.results / 'lief-debug-archives.json').is_file())

    def test_shared_build_does_not_hide_tool_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            runner = mock.Mock()
            runner.run.side_effect = RuntimeError('node_mksnapshot failed')
            with mock.patch.object(helper, 'state', return_value=(work, work / 'node', {'bundled': False}, runner)), \
                    mock.patch.object(helper.sys, 'platform', 'win32'):
                with self.assertRaisesRegex(RuntimeError, 'node_mksnapshot failed'):
                    helper.build_node(SimpleNamespace(jobs=4))

    def test_only_the_observed_signing_skip_is_classified_as_blocked(self):
        known = ('[process 12]: --- stderr ---\n'
                 'SignTool Error: File not found: SHA256\n'
                 '1..0 # Skipped: Cannot sign C:\\test\\sea.exe\n')
        self.assertEqual(helper.classify_existing_probe(0, known, True),
                         'blocked-by-existing-signtool-verify-argument')
        for code, output, legacy in [
                (1, known, True), (0, known, False),
                (0, known.replace('SHA256\n', 'SHA256.lib\n'), True),
                (0, known.replace('File not found: SHA256', 'certificate is not trusted'), True),
                (0, '1..0 # Skipped: LIEF is disabled\n', True),
                (0, 'SignTool Error: File not found: SHA256\n1..0 # Skipped: another issue\n', True)]:
            with self.subTest(code=code, output=output, legacy=legacy):
                self.assertEqual(helper.classify_existing_probe(code, output, legacy),
                                 'failed-or-unexpected-skip')
        self.assertEqual(helper.classify_existing_probe(0, '', True), 'passed')

    def test_fixture_stdout_is_checked_separately_from_warning_stderr(self):
        with tempfile.TemporaryDirectory() as temporary:
            results = Path(temporary)
            runner = helper.Runner(results)
            output = runner.run_stdout('stdout-check', [sys.executable, '-c',
                'import sys; print("payload 😊"); print("warning", file=sys.stderr)'], results,
                env=os.environ.copy())
            self.assertEqual(output, 'payload 😊\n')
            self.assertEqual((results / 'stdout-check.stderr.log').read_text(), 'warning\n')
            with self.assertRaises(RuntimeError):
                runner.run_stdout('exit-check', [sys.executable, '-c',
                    'import sys; print("payload"); sys.exit(1)'], results, env=os.environ.copy())

    def test_push_and_dispatch_use_exactly_the_requested_four_variants(self):
        with tempfile.TemporaryDirectory() as temporary:
            for event in ['push', 'workflow_dispatch']:
                env = os.environ.copy()
                env.update(GITHUB_EVENT_NAME=event, GITHUB_OUTPUT=str(Path(temporary) / event))
                result = subprocess.run([sys.executable, helper_path, 'matrix'], env=env,
                                        capture_output=True, text=True, check=True)
                rows = json.loads(result.stdout)
                self.assertEqual({row['variant'] for row in rows}, {
                    'bundled-0.17.0', 'bundled-1.0.0', 'shared-0.17.0', 'shared-1.0.0'})
                self.assertEqual(len(rows), 4)
                self.assertTrue(all(row['arch'] == 'x64' and row['runner'] == 'windows-2022'
                                    and row['execute_sea'] for row in rows))


if __name__ == '__main__':
    unittest.main()
