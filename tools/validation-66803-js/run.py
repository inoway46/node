"""Reuse artifact 12165443477; never configure, compile, or select a host Node."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[2]
DRIVER = Path(__file__).resolve().parent
AUDIT = Path(os.environ.get('AUDIT', ROOT / 'audit-js-regression')).resolve()
ARTIFACT = Path(os.environ.get('BUILD_ARTIFACT', '/tmp/issue-66803-build-artifact')).resolve()
SOURCE = Path(os.environ.get('TEST_SOURCE', '/tmp/issue-66803-js-source')).resolve()
BUNDLE = Path(os.environ.get('NODE_BUNDLE', '/tmp/issue-66803-node-bundle')).resolve()
NODE = SOURCE / 'out/Release/node'
BASE = 'f59539b514344ed0a0945f8790d61121df88a5d4'
CPU = 'rv64,v=false,zba=false,zbb=false,zbc=false,zbs=false'
PATCH_SHA = '26d23edc44b38bb9a82ba32505ff6ba4f08ffd514d05144811a2607a95dc7bd7'
NODE_SHA = 'cca346fd8e38298630c715791efcc7ba4be50768ff64467da97e58e11d8b005c'
TAR_SHA = '558260c17b64375398f52ed7a2da6e44f99858f8551e3b071cf7c566e9e158bb'
CONFIG_SHA = '59eff2cb086cb7a7d5a99c43dd6a9be9a618851d5316d72fb928b97eeb7106b0'
CORE = [
    'parallel/test-buffer-alloc',
    'parallel/test-buffer-compare',
    'parallel/test-buffer-tojson',
    'parallel/test-string-decoder',
    'parallel/test-string-decoder-end',
    'parallel/test-require-json',
    'parallel/test-fs-exists',
    'parallel/test-fs-readfile-empty',
    'parallel/test-fs-readfile-fd',
    'parallel/test-worker-message-channel',
    'parallel/test-child-process-fork',
    'parallel/test-child-process-fork-exec-argv',
]
TEMPORAL = [
    'parallel/test-temporal',
    'parallel/test-temporal-with-zoneinfo',
    'parallel/test-fs-stat-temporal',
]
SCOPES = ('small', 'parallel', 'sequential', 'message', 'js-suites')


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def verify(path, expected):
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise RuntimeError(f'SHA256 mismatch: {path}: {actual} != {expected}')


def command(args, name, cwd=SOURCE, timeout=180, env=None):
    """Keep both streams and exit status, including on timeout or spawn failure."""
    args = [str(arg) for arg in args]
    record = {'argv': args, 'cwd': str(cwd), 'timeout_seconds': timeout}
    write_json(AUDIT / f'{name}.command.json', record)
    print(f'[{name}] {shlex.join(args)}', flush=True)
    started = time.monotonic()
    with (AUDIT / f'{name}.stdout').open('wb') as out, \
            (AUDIT / f'{name}.stderr').open('wb') as err:
        try:
            proc = subprocess.Popen(args, cwd=cwd, env=env, stdout=out, stderr=err,
                                    start_new_session=True)
        except OSError as error:
            record.update(exit_code=127, spawn_error=str(error), timed_out=False)
        else:
            try:
                record['exit_code'] = proc.wait(timeout=timeout)
                record['timed_out'] = False
            except subprocess.TimeoutExpired:
                record.update(exit_code=124, timed_out=True)
            finally:
                # Also reap helpers left behind by a test runner or preflight.
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
    record['elapsed_seconds'] = round(time.monotonic() - started, 3)
    write_json(AUDIT / f'{name}.result.json', record)
    print(f'[{name}] exit={record["exit_code"]}, elapsed={record["elapsed_seconds"]}s',
          flush=True)
    return record['exit_code']


def checked(args, name, cwd=SOURCE):
    if command(args, name, cwd):
        raise RuntimeError(f'{name} failed; see {name}.stderr / .stdout')


def prepare():
    (AUDIT / 'state.txt').write_text('source-or-bundle-preparation\n')
    evidence = AUDIT / 'original-build'
    evidence.mkdir(exist_ok=True)
    for name in ('conditions.json', 'node-bundle.json', 'config.gypi', 'applied.patch',
                 'final-applied.patch', 'qemu-command.json', 'runtime-libraries.json',
                 'node-version.log', 'node-smoke.log', 'qemu-version.log',
                 'build-exit-code'):
        shutil.copy2(ARTIFACT / name, evidence / name)
    verify(ARTIFACT / 'applied.patch', PATCH_SHA)
    verify(ARTIFACT / 'final-applied.patch', PATCH_SHA)
    verify(ARTIFACT / 'node-runtime.tar.gz', TAR_SHA)
    verify(ARTIFACT / 'config.gypi', CONFIG_SHA)
    conditions = json.loads((ARTIFACT / 'conditions.json').read_text())
    manifest = json.loads((ARTIFACT / 'node-bundle.json').read_text())
    if conditions['base'] != BASE or conditions['qemu_cpu'] != CPU:
        raise RuntimeError('Unexpected source base or CPU in build conditions')
    if manifest['sha256'] != NODE_SHA or manifest['qemu_cpu'] != CPU:
        raise RuntimeError('Unexpected bundle manifest')
    if (ARTIFACT / 'build-exit-code').read_text().strip() != '0':
        raise RuntimeError('Original build did not succeed')
    if SOURCE.exists() or BUNDLE.exists():
        raise RuntimeError('Refusing to overwrite existing source/bundle; use fresh paths')
    checked(['git', 'worktree', 'add', '--detach', SOURCE, BASE], 'checkout-source', ROOT)
    checked(['git', 'apply', '--check', ARTIFACT / 'final-applied.patch'], 'patch-check')
    # This is the cumulative diff, including both PRs and the candidate V8 fixes.
    # Do not apply the individual PR or candidate patches as well.
    checked(['git', 'apply', ARTIFACT / 'final-applied.patch'], 'patch-apply')
    checked(['git', 'diff', '--check'], 'source-diff-check')
    checked(['git', '-c', 'core.abbrev=8', 'diff', '--binary'], 'restored-source-diff')
    verify(AUDIT / 'restored-source-diff.stdout', PATCH_SHA)
    BUNDLE.mkdir()
    libraries = {'libatomic.so.1', 'libstdc++.so.6', 'libgcc_s.so.1', 'libc.so.6',
                 'libm.so.6', 'ld-linux-riscv64-lp64d.so.1'}
    allowed = {'node', 'config.gypi', 'node-bundle.json', 'smoke.js'} | {
        f'runtime/lib/{name}' for name in libraries}
    with tarfile.open(ARTIFACT / 'node-runtime.tar.gz') as archive:
        members = archive.getmembers()
        if {m.name for m in members} != allowed or len(members) != len(allowed):
            raise RuntimeError('Unexpected bundle contents')
        for member in members:
            if not member.isfile():
                raise RuntimeError(f'Non-regular bundle member: {member.name}')
            dest = BUNDLE / member.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as src, dest.open('wb') as dst:
                shutil.copyfileobj(src, dst)
            dest.chmod(member.mode & 0o777)
    verify(BUNDLE / 'node', NODE_SHA)
    verify(BUNDLE / 'config.gypi', CONFIG_SHA)
    if json.loads((BUNDLE / 'node-bundle.json').read_text()) != manifest:
        raise RuntimeError('Inner and outer bundle manifests differ')
    header = (BUNDLE / 'node').read_bytes()[:20]
    if header[:6] != b'\x7fELF\x02\x01' or int.from_bytes(header[18:20], 'little') != 243:
        raise RuntimeError('Saved Node is not a little-endian RISC-V ELF64')
    NODE.parent.mkdir(parents=True)
    shutil.copy2(BUNDLE / 'node', NODE)
    NODE.chmod(0o755)
    shutil.copy2(BUNDLE / 'config.gypi', SOURCE / 'config.gypi')
    write_json(AUDIT / 'provenance.json', {
        'repository': 'inoway46/node', 'run_id': 39183959521,
        'artifact_id': 12165443477, 'artifact_name': 'issue-66803-temporal-full-build',
        'original_workflow_sha': '6ae176d001815235f2d5f5eecdad2c4b2aa0dab5',
        'source_base': BASE, 'cumulative_patch_sha256': PATCH_SHA,
        'node_sha256': NODE_SHA, 'runtime_tar_sha256': TAR_SHA,
        'config_sha256': CONFIG_SHA, 'qemu_cpu': CPU,
    })
    (AUDIT / 'state.txt').write_text('prepared; preflight-not-run\n')


def target_env():
    verify(NODE, NODE_SHA)
    env = os.environ.copy()
    for name in ('NODE_OPTIONS', 'NODE_PATH', 'NODE_REPL_EXTERNAL_MODULE', 'LD_PRELOAD',
                 'LD_LIBRARY_PATH', 'QEMU_UNSET_ENV'):
        env.pop(name, None)
    env.update(QEMU_CPU=CPU, QEMU_LD_PREFIX=str(BUNDLE / 'runtime'),
               QEMU_SET_ENV=f'LD_LIBRARY_PATH={BUNDLE}/runtime/lib',
               EXPECTED_NODE=str(NODE))
    # Test code that invokes `node` via PATH must also get this RISC-V ELF.
    env['PATH'] = f'{NODE.parent}:{env["PATH"]}'
    write_json(AUDIT / 'target-environment.json', {
        name: env[name] for name in ('QEMU_CPU', 'QEMU_LD_PREFIX', 'QEMU_SET_ENV',
                                    'EXPECTED_NODE', 'PATH')})
    return env


def preflight():
    (AUDIT / 'state.txt').write_text('environment-preflight\n')
    env = target_env()
    checked(['readelf', '-h', '-l', '-d', NODE], 'target-elf')
    for name, args in (
        ('target-version', ['--version']),
        ('direct-elf-spawn-fork-worker', [DRIVER / 'preflight.cjs']),
        ('temporal-capability', ['--harmony-temporal', '-e',
         "require('node:assert/strict').equal(typeof Temporal, 'object')"]),
    ):
        if command([NODE, *args], name, timeout=180, env=env):
            raise RuntimeError(f'Preflight failed: {name}; core tests were not run')
    (AUDIT / 'state.txt').write_text('preflight-passed\n')


def inventory(selectors):
    entries = []
    for suite in ('parallel', 'sequential', 'message'):
        pattern = '*' if suite == 'message' else 'test-*'
        for path in sorted((SOURCE / 'test' / suite).glob(pattern)):
            if path.suffix not in ('.js', '.mjs'):
                continue
            name = f'{suite}/{path.stem}'
            if not any(name == item or suite == item for item in selectors):
                continue
            text = path.read_text()
            entries.append({
                'test': name, 'file': str(path.relative_to(SOURCE)),
                'flags': re.findall(r'//\s*Flags:(.*)', text),
                'native_dependency_hints': [line.strip() for line in text.splitlines()
                    if not line.lstrip().startswith('//') and
                    re.search(r'\.node\b|common\.buildType|cctest|build/Release|'
                                 r'fixtures\.(?:path|join)\(.*(?:snapshot|sea|embedder)', line)],
            })
    write_json(AUDIT / 'selected-tests.json', entries)
    status = AUDIT / 'status-rules'
    status.mkdir(exist_ok=True)
    for path in (SOURCE / 'test').glob('**/*.status'):
        dest = status / path.relative_to(SOURCE / 'test')
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
    return entries


def test():
    if (AUDIT / 'state.txt').read_text().strip() != 'preflight-passed':
        raise RuntimeError('A successful direct ELF preflight is required')
    scope = os.environ.get('TEST_SCOPE', 'small')
    if scope not in SCOPES:
        raise ValueError(f'Unknown scope: {scope}')
    selectors = CORE + TEMPORAL if scope == 'small' else (
        ['parallel', 'sequential', 'message'] if scope == 'js-suites' else [scope])
    entries = inventory(selectors)
    if scope == 'small' and {e['test'] for e in entries} != set(selectors):
        raise RuntimeError('A selected small test is missing from the restored source')
    groups = [('core', CORE, []), ('temporal', TEMPORAL, ['--node-args=--harmony-temporal'])] \
        if scope == 'small' else [(scope, selectors, [])]
    (AUDIT / 'state.txt').write_text('tests-running\n')
    env = target_env()
    failed = False
    for name, selection, extra in groups:
        args = [sys.executable, '-u', SOURCE / 'tools/test.py',
                '--shell', NODE, '--mode=release', '-j', '1', '--timeout=300',
                '--progress=tap', '--logfile', AUDIT / f'{name}.tap',
                '--verbose', '--report', '--time', '--flaky-tests=run',
                *extra, *selection]
        # On ubuntu x64, test.py uses the ia32 release multiplier (1): 300s/test.
        # No repeats, flakiness measurement, global feature disables, or builds.
        code = command(args, name, timeout=1800 if scope == 'small' else 8400, env=env)
        tap_path = AUDIT / f'{name}.tap'
        tap = tap_path.read_text(errors='replace') if tap_path.exists() else ''
        plan = re.search(r'^1\.\.(\d+)$', tap, re.M)
        completed = len(re.findall(r'^(?:not ok|ok) \d+ ', tap, re.M))
        # test.py can exit 0 with no cases if a binary probe fails. Never report
        # that as successful regression coverage, or accept a truncated TAP file.
        if not plan or int(plan[1]) == 0 or int(plan[1]) != completed:
            (AUDIT / f'{name}-incomplete.txt').write_text(
                f'TAP plan missing/zero/incomplete: plan={plan[1] if plan else None}, '
                f'completed={completed}; runner exit={code}\n')
            code = code or 1
        failed |= code != 0
    (AUDIT / 'state.txt').write_text('tests-failed\n' if failed else 'tests-passed\n')
    return 1 if failed else 0


def summarize():
    state = (AUDIT / 'state.txt').read_text().strip() if (AUDIT / 'state.txt').exists() \
        else 'setup-incomplete'
    rows = []
    suspects = []
    for path in sorted(AUDIT.glob('*.tap')):
        text = path.read_text(errors='replace')
        results = re.findall(r'^(not ok|ok) \d+ .*$', text, re.M)
        skipped = len(re.findall(r'^ok \d+ .*# skip\b', text, re.M | re.I))
        failed = results.count('not ok')
        plan = re.search(r'^1\.\.(\d+)$', text, re.M)
        row = {'group': path.stem, 'planned': int(plan[1]) if plan else None,
               'completed': len(results), 'passed': results.count('ok') - skipped,
               'failed': failed, 'runtime_skipped': skipped,
               'timeouts': len(re.findall(r'^\s+timeout$', text, re.M))}
        stdout = AUDIT / f'{path.stem}.stdout'
        report = stdout.read_text(errors='replace') if stdout.exists() else ''
        status_skip = re.search(r'\*\s+(\d+) tests will be skipped', report)
        row['status_rule_skipped'] = int(status_skip[1]) if status_skip else None
        row['incomplete_tap'] = (AUDIT / f'{path.stem}-incomplete.txt').exists()
        result = AUDIT / f'{path.stem}.result.json'
        if result.exists():
            row.update(json.loads(result.read_text()))
        rows.append(row)
        # These are investigation hints, never an automatic reclassification to PASS.
        for line in text.splitlines():
            if re.search(r'Cannot find module.*(?:\.node|test/addons|(?:out|build)/Release)|'
                         r'cctest.*ENOENT|spawn .*ENOENT|'
                         r'(?:build/Release|out/Release).*ENOENT|'
                         r'error while loading shared libraries', line):
                suspects.append({'group': path.stem, 'evidence': line.strip()})
    write_json(AUDIT / 'summary.json', {'state': state, 'groups': rows,
                                      'possible_missing_prerequisites': suspects})
    lines = [f'State: **{state}**', '',
             '| Group | Planned | Completed | Pass | Fail | Runtime skip | Status skip | Timeout | Exit |',
             '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for row in rows:
        lines.append('| ' + ' | '.join(str(row.get(key, '?')) for key in (
            'group', 'planned', 'completed', 'passed', 'failed', 'runtime_skipped',
            'status_rule_skipped', 'timeouts', 'exit_code')) + ' |')
    lines += ['', 'Status-rule skips are reported in each group .stdout (--report); '
              'they are outside the TAP plan. Suite wall timeouts are in .result.json.',
              '', 'Setup failure means prerequisites are incomplete. A preflight failure '
              'blocks core tests and needs investigation of both runtime and environment. '
              'Missing-native hints need review and do not turn a failure into a pass.',
              '', 'Inspect *.tap, *.stdout, *.stderr, *.command.json, *.result.json, '
              'selected-tests.json, status-rules/, and original-build/.',
              '', 'QEMU results cover only the selected tests. RISC-V hardware, the full '
              'Node test suite, and correctness of the candidate V8 fixes remain unverified.']
    if suspects:
        lines += ['', 'Possible missing prerequisites:', *[
            f'- {item["group"]}: `{item["evidence"].replace("`", "")}`' for item in suspects]]
    (AUDIT / 'summary.md').write_text('\n'.join(lines) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'preflight', 'test', 'summarize'))
    args = parser.parse_args()
    AUDIT.mkdir(parents=True, exist_ok=True)
    try:
        return globals()[args.action]() or 0
    except Exception as error:
        (AUDIT / f'{args.action}-error.txt').write_text(f'{type(error).__name__}: {error}\n')
        if args.action != 'summarize':
            (AUDIT / 'state.txt').write_text(f'{args.action}-failed\n')
        print(f'{type(error).__name__}: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
