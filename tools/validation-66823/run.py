"""Validate the exact PR source through generated Rust build rules and FFI."""
import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys

SHA = '19c93459614359c7d94ab65b807606e40ffce71b'
HOST = 'x86_64-unknown-linux-gnu'
TARGET = 'riscv64gc-unknown-linux-gnu'
GENERATOR, PROFILE = sys.argv[1:]
ROOT = Path.cwd()
RESULTS = ROOT / 'results'
RESULTS.mkdir(exist_ok=True)
TREE = Path(os.environ['RUNNER_TEMP']) / 'pr-source'
ENV = dict(os.environ, CC='riscv64-linux-gnu-gcc-14', CXX='riscv64-linux-gnu-g++-14',
           CC_host='clang-19', CXX_host='clang++-19', AR='riscv64-linux-gnu-ar',
           AR_host='ar', PYTHONHASHSEED='0', CARGO_TERM_VERBOSE='true',
           CARGO_TARGET_RISCV64GC_UNKNOWN_LINUX_GNU_LINKER='riscv64-linux-gnu-gcc-14')
for key in ['CARGO_BUILD_TARGET', 'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'GYP_CROSSCOMPILE']:
    ENV.pop(key, None)


def run(command, label, cwd=None, env=None):
    print('+', ' '.join(map(str, command)), flush=True)
    result = subprocess.run(command, cwd=cwd or TREE, env=env or ENV,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
    (RESULTS / (label + '.log')).write_text(result.stdout)
    if result.returncode:
        print(result.stdout[-16000:], flush=True)
        raise RuntimeError(f'{label}: exit {result.returncode}')
    return result.stdout


def check_isa(path, label):
    headers = run(['riscv64-linux-gnu-readelf', '-h', str(path)], label + '-headers')
    machines = re.findall(r'Machine:\s+([^\n]+)', headers)
    assert machines and set(machines) == {'RISC-V'}, label
    flags = re.findall(r'Flags:\s+([^\n]+)', headers)
    assert flags and all('double-float ABI' in f for f in flags), label
    attrs = run(['riscv64-linux-gnu-readelf', '-A', str(path)], label + '-attributes')
    arches = re.findall(r'Tag_RISCV_arch: "([^"]+)"', attrs)
    assert arches, label
    # Decomposed extensions already implied by rv64gc are permitted.
    allowed = {'i', 'm', 'a', 'f', 'd', 'c', 'zicsr', 'zifencei', 'zmmul',
               'zaamo', 'zalrsc', 'zca', 'zcd'}
    for arch in arches:
        assert arch.startswith('rv64'), arch
        extensions = {re.sub(r'\d+p\d+$', '', part) for part in arch[4:].split('_')}
        assert extensions <= allowed, (label, arch, extensions - allowed)


run(['git', 'worktree', 'add', '--detach', str(TREE), SHA], 'checkout', ROOT)
assert run(['git', 'rev-parse', 'HEAD'], 'source-sha').strip() == SHA
for label, command in [
    ('rustc', ['rustc', '-vV']), ('cargo', ['cargo', '-V']),
    ('host-compiler', ['clang-19', '--version']),
    ('target-compiler', ['riscv64-linux-gnu-gcc-14', '-v']),
    ('target-defaults', ['riscv64-linux-gnu-gcc-14', '-Q', '--help=target']),
    ('qemu', ['qemu-riscv64', '--version']),
]:
    run(command, label)
for name in ['libc.so.6', 'libm.so.6', 'libstdc++.so.6', 'libgcc_s.so.1', 'ld-linux-riscv64-lp64d.so.1']:
    lib = Path(run(['riscv64-linux-gnu-gcc-14', '-print-file-name=' + name], 'locate-' + name).strip())
    assert lib.is_file(), lib
    check_isa(lib, 'sysroot-' + name)
flags = ['--cross-compiling', '--dest-os=linux', '--dest-cpu=riscv64', '--v8-enable-temporal-support']
if GENERATOR == 'ninja':
    flags.append('--ninja')
if PROFILE == 'Debug':
    flags.append('--debug')
run(['./configure', *flags], 'configure', env=dict(ENV, CARGO_BUILD_TARGET=TARGET))
config = (TREE / 'config.gypi').read_text()
(RESULTS / 'config.gypi').write_text(config)
v = ast.literal_eval(config)['variables']
assert v['v8_enable_temporal_support'] == 1
assert v['cargo_rust_target_host'] == HOST and v['cargo_rust_target_target'] == TARGET
assert 'CARGO_BUILD_TARGET' not in ENV
out = TREE / 'out' / PROFILE if GENERATOR == 'ninja' else TREE / 'out'
gen = TREE / 'out' / PROFILE / ('gen' if GENERATOR == 'ninja' else 'obj/gen')
archives = {role: gen / 'cargo' / role / triple / PROFILE.lower() / 'libnode_crates.a'
            for role, triple in [('host', HOST), ('target', TARGET)]}
command = (['ninja', '-C', str(out), '-j2', '-v', *[str(a.relative_to(out)) for a in archives.values()]]
           if GENERATOR == 'ninja' else ['make', '-C', str(out), '-j2', 'BUILDTYPE=' + PROFILE, 'V=1', 'node_crates'])
run(command, 'build')
stamps = [a.stat().st_mtime_ns for a in archives.values()]
run(command, 'incremental')
assert stamps == [a.stat().st_mtime_ns for a in archives.values()]
code = TREE / 'probe.c'
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
for role, archive in archives.items():
    exe = TREE / ('probe-' + role)
    compiler = ['clang-19'] if role == 'host' else ['riscv64-linux-gnu-gcc-14', '-march=rv64gc', '-mabi=lp64d']
    if role == 'target':
        check_isa(archive, 'target-archive')
    else:
        h = run(['readelf', '-h', str(archive)], 'host-archive')
        assert set(re.findall(r'Machine:\s+([^\n]+)', h)) == {'Advanced Micro Devices X86-64'}
    run([*compiler, '-std=c11', '-I', str(TREE / 'deps/crates/vendor/temporal_capi-v0_2/bindings/c'),
         str(code), str(archive), '-ldl', '-lpthread', '-lm', '-lrt', '-lutil', '-o', str(exe)], role + '-link')
    if role == 'target':
        check_isa(exe, 'target-executable')
        run(['readelf', '-d', str(exe)], 'target-dynamic')
        run(['qemu-riscv64', '-cpu', 'rv64,v=false,zba=false,zbb=false,zbc=false,zbs=false',
             '-L', '/usr/riscv64-linux-gnu', str(exe)], 'target-execute')
    else:
        run([str(exe)], 'host-execute')
assert not run(['git', 'diff', '--name-only'], 'source-diff').strip()
(RESULTS / 'success.json').write_text(json.dumps({'source': SHA, 'generator': GENERATOR,
                                                'profile': PROFILE, 'host_and_target_ffi': 'passed',
                                                'full_node_build': False}, indent=2))
