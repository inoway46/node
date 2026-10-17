"""Validate only the shared-producer patch in a Temporal-disabled RISC-V build."""
import ast
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1]
BASE = '3ba72b0b9c70d44f35ebd19401431e2f80aa6c62'
GENERATOR = sys.argv[1]
STAGE, PHASE = 'cross', 'shared-only'
RESULTS = SOURCE / 'shared-only-results'
RESULTS.mkdir(exist_ok=True)
TREE = Path(os.environ['RUNNER_TEMP']) / 'node-full'
ENV = dict(os.environ, CC='clang-19', CXX='clang++-19', PYTHONHASHSEED='0', CARGO_TERM_VERBOSE='true')
for key in ['CARGO_BUILD_TARGET', 'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'GYP_CROSSCOMPILE']:
    ENV.pop(key, None)
STATUS = {'stage': STAGE, 'generator': GENERATOR, 'phase': PHASE, 'base': BASE, 'commands': []}


def run(command, cwd, label):
    print('+', ' '.join(map(str, command)), flush=True)
    start = time.monotonic()
    with (RESULTS / (label + '.log')).open('w') as output:
        result = subprocess.run(command, cwd=cwd, env=ENV, stdout=output, stderr=subprocess.STDOUT, check=False)
    STATUS['commands'].append({'label': label, 'command': command, 'returncode': result.returncode,
                               'seconds': round(time.monotonic() - start, 2)})
    (RESULTS / 'status.json').write_text(json.dumps(STATUS, indent=2))
    if result.returncode:
        print((RESULTS / (label + '.log')).read_text()[-16000:], flush=True)
    return result.returncode


def required(command, cwd, label):
    if run(command, cwd, label):
        sys.exit(1)


for tool in [['clang-19', '--version'], ['ld', '--version']]:
    required(tool, SOURCE, tool[0] + '-version')
required(['git', 'worktree', 'add', '--detach', str(TREE), BASE], SOURCE, 'checkout')
for name in ['single-producer']:
    patch = TREE / (name + '.patch')
    patch.write_bytes(base64.b64decode((HERE / (name + '.patch.b64')).read_bytes()))
    required(['git', 'apply', str(patch)], TREE, name + '-apply')
flags = ['--v8-disable-temporal-support']
if GENERATOR == 'ninja':
    flags.append('--ninja')
if STAGE == 'cross':
    target_flags = ' --target=riscv64-linux-gnu --gcc-toolchain=/usr -march=rv64gc -mabi=lp64d'
    ENV.update(CC='clang-19' + target_flags, CXX='clang++-19' + target_flags, AR='riscv64-linux-gnu-ar',
               CC_host='clang-19', CXX_host='clang++-19', AR_host='ar',
               CC_target='clang-19' + target_flags, CXX_target='clang++-19' + target_flags, AR_target='riscv64-linux-gnu-ar')
    flags += ['--cross-compiling', '--dest-os=linux', '--dest-cpu=riscv64']
    required(['riscv64-linux-gnu-gcc', '--version'], TREE, 'cross-gcc-version')
    required(['riscv64-linux-gnu-ld', '--version'], TREE, 'cross-ld-version')
required(['./configure', *flags], TREE, 'configure')
shutil.copy(TREE / 'config.gypi', RESULTS / 'config.gypi')
config = ast.literal_eval((TREE / 'config.gypi').read_text())
assert config['variables']['v8_enable_temporal_support'] == 0
assert 'cargo_cross_compiling' not in config['variables']
required(['git', 'diff'], TREE, 'applied-diff')
required(['git', 'diff', '--name-only'], TREE, 'changed-files')
assert set((RESULTS / 'changed-files.log').read_text().splitlines()) == {
    'deps/crates/crates.gyp', 'src/inspector/node_inspector.gypi', 'tools/v8_gypfiles/d8.gyp',
    'tools/v8_gypfiles/v8.gyp', 'tools/v8_gypfiles/v8_debug_helper.gyp',
}
OUT = TREE / 'out'
PREFIX = (['ninja', '-C', str(OUT / 'Release'), '-j2', '-v'] if GENERATOR == 'ninja' else
          ['make', '-C', str(OUT), '-j2', 'BUILDTYPE=Release', 'V=1'])
if GENERATOR == 'ninja':
    run(['ninja', '-C', str(OUT / 'Release'), '-t', 'commands', 'node'], TREE, 'all-build-commands')
else:
    run(['make', '-C', str(OUT), '-n', 'BUILDTYPE=Release', 'V=1', 'node'], TREE, 'all-build-commands')
commands = (RESULTS / 'all-build-commands.log').read_text()
assert 'cargo rustc' not in commands
failures = []
if STAGE == 'cross':
    failures.append(run([*PREFIX, 'mksnapshot'], TREE, 'mksnapshot-build'))
    if (OUT / 'Release/mksnapshot').exists():
        failures.append(run(['readelf', '-h', str(OUT / 'Release/mksnapshot')], TREE, 'mksnapshot-elf'))
        assert 'Advanced Micro Devices X86-64' in (RESULTS / 'mksnapshot-elf.log').read_text()
        failures.append(run([str(OUT / 'Release/mksnapshot'), '--help'], TREE, 'mksnapshot-help'))
    else:
        failures.append(1)
failures.append(run([*PREFIX, 'node'], TREE, 'node-build'))
if (OUT / 'Release/node').exists():
    failures.append(run(['readelf', '-h', str(OUT / 'Release/node')], TREE, 'node-elf'))
    assert 'RISC-V' in (RESULTS / 'node-elf.log').read_text()
    executable = (['qemu-riscv64', '-L', '/usr/riscv64-linux-gnu'] if STAGE == 'cross' else []) + [str(OUT / 'Release/node')]
    failures.append(run([*executable, '--version'], TREE, 'node-version'))
    if STAGE == 'native':
        failures.append(run([*executable, '--harmony-temporal', '-e',
                             'if (Temporal.PlainDate.from("2024-02-29").month !== 2) process.exit(1)'], TREE, 'node-temporal'))
else:
    failures.append(1)
STATUS['success'] = not any(failures)
(RESULTS / 'status.json').write_text(json.dumps(STATUS, indent=2))
sys.exit(1 if any(failures) else 0)
