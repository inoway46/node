"""Isolated real Cargo actions and Temporal ABI probes, for fork GHA only."""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1]
BASE = '3ba72b0b9c70d44f35ebd19401431e2f80aa6c62'
HOST = 'x86_64-unknown-linux-gnu'
TARGET = 'riscv64gc-unknown-linux-gnu'
STAGE, GENERATOR, PROFILE = sys.argv[1:]
RESULTS = SOURCE / 'results'
RESULTS.mkdir(exist_ok=True)
ENV = dict(os.environ, CC='clang-19', CXX='clang++-19', PYTHONHASHSEED='0', CARGO_TERM_VERBOSE='true')
for key in ['CARGO_BUILD_TARGET', 'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'GYP_CROSSCOMPILE']:
    ENV.pop(key, None)


def run(command, cwd, label):
    print('+', ' '.join(map(str, command)), flush=True)
    with (RESULTS / (label + '.log')).open('w') as output:
        result = subprocess.run(command, cwd=cwd, env=ENV, stdout=output, stderr=subprocess.STDOUT, check=False)
    if result.returncode:
        print((RESULTS / (label + '.log')).read_text()[-18000:], flush=True)
        raise subprocess.CalledProcessError(result.returncode, command)


def probe(tree, archive, machine, label):
    code = tree / 'probe.c'
    code.write_text('''#include "PlainDate.h"
int main(void) {
  temporal_rs_PlainDate_try_new_result d =
      temporal_rs_PlainDate_try_new(2024, 2, 29, AnyCalendarKind_Iso);
  if (!d.is_ok) return 1;
  int result = temporal_rs_PlainDate_is_valid(d.ok) &&
      temporal_rs_PlainDate_year(d.ok) == 2024 &&
      temporal_rs_PlainDate_month(d.ok) == 2 ? 0 : 2;
  temporal_rs_PlainDate_destroy(d.ok);
  return result;
}
''')
    compiler = 'riscv64-linux-gnu-gcc' if machine == 'RISC-V' else 'clang-19'
    exe = tree / ('probe-' + label)
    run([compiler, '-std=c11', '-I', str(tree / 'deps/crates/vendor/temporal_capi-v0_2/bindings/c'),
         str(code), str(archive), '-ldl', '-lpthread', '-lm', '-lrt', '-lutil', '-o', str(exe)], tree, label + '-link')
    run(['readelf', '-h', str(exe)], tree, label + '-elf')
    assert machine in (RESULTS / (label + '-elf.log')).read_text()
    run(['readelf', '-h', str(archive)], tree, label + '-archive')
    headers = (RESULTS / (label + '-archive.log')).read_text()
    assert machine in headers
    assert ('RISC-V' not in headers) if machine != 'RISC-V' else ('Advanced Micro Devices X86-64' not in headers)
    command = ['qemu-riscv64', '-L', '/usr/riscv64-linux-gnu', str(exe)] if machine == 'RISC-V' else [str(exe)]
    run(command, tree, label + '-execute')


def build(phase):
    tree = Path(os.environ['RUNNER_TEMP']) / ('node-' + phase)
    run(['git', 'clone', '--shared', '--no-checkout', str(SOURCE), str(tree)], SOURCE, phase + '-clone')
    run(['git', 'checkout', '--detach', BASE], tree, phase + '-checkout')
    patch = tree / 'shared.patch'
    patch.write_bytes(base64.b64decode((HERE / 'single-producer.patch.b64').read_bytes()))
    run(['git', 'apply', str(patch)], tree, phase + '-shared-patch')
    if phase == 'after':
        patch = tree / 'rust.patch'
        patch.write_bytes(base64.b64decode((HERE / 'rust-cross-only.patch.b64').read_bytes()))
        run(['git', 'apply', str(patch)], tree, phase + '-rust-patch')
    flags = ['--v8-enable-temporal-support']
    if GENERATOR == 'ninja':
        flags.append('--ninja')
    if PROFILE == 'Debug':
        flags.append('--debug')
    if STAGE == 'cross':
        ENV.update(CC='riscv64-linux-gnu-gcc', CXX='riscv64-linux-gnu-g++', AR='riscv64-linux-gnu-ar',
                   CC_host='clang-19', CXX_host='clang++-19', AR_host='ar',
                   CC_target='riscv64-linux-gnu-gcc', CXX_target='riscv64-linux-gnu-g++', AR_target='riscv64-linux-gnu-ar',
                   CARGO_TARGET_RISCV64GC_UNKNOWN_LINUX_GNU_LINKER='riscv64-linux-gnu-gcc')
        flags += ['--cross-compiling', '--dest-os=linux', '--dest-cpu=riscv64',
                  '--rust-host-target=' + HOST, '--rust-target=' + TARGET]
    run(['./configure', *flags], tree, phase + '-configure')
    shutil.copy(tree / 'config.gypi', RESULTS / (phase + '-config.gypi'))
    root = tree / 'out' / PROFILE
    gen = root / ('gen' if GENERATOR == 'ninja' else 'obj/gen')
    if STAGE == 'cross':
        archives = [(gen / 'cargo/host' / HOST / PROFILE.lower() / 'libnode_crates.a', 'Advanced Micro Devices X86-64', 'host'),
                    (gen / 'cargo/target' / TARGET / PROFILE.lower() / 'libnode_crates.a', 'RISC-V', 'target')]
    else:
        archives = [(gen / PROFILE.lower() / 'libnode_crates.a', 'Advanced Micro Devices X86-64', 'native')]
    out = root if GENERATOR == 'ninja' else tree / 'out'
    targets = [str(a.relative_to(out)) for a, _, _ in archives]
    command = (['ninja', '-C', str(out), '-j2', '-v'] if GENERATOR == 'ninja' else
               ['make', '-C', str(out), '-j2', 'BUILDTYPE=' + PROFILE, 'V=1']) + targets
    run(command, tree, phase + '-cargo')
    stamps = [a.stat().st_mtime_ns for a, _, _ in archives]
    run(command, tree, phase + '-incremental')
    assert stamps == [a.stat().st_mtime_ns for a, _, _ in archives]
    for archive, machine, toolset in archives:
        probe(tree, archive, machine, phase + '-' + toolset)
    (RESULTS / (phase + '-success.json')).write_text(json.dumps({'phase': phase, 'stage': STAGE,
                                                               'generator': GENERATOR, 'profile': PROFILE, 'archives': targets}, indent=2))
    shutil.rmtree(tree)


for tool in [['rustc', '-vV'], ['cargo', '-V'], ['clang-19', '--version']]:
    run(tool, SOURCE, tool[0] + '-version')
for phase in (['before', 'after'] if STAGE == 'native' else ['after']):
    build(phase)
