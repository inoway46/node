"""Prepare the three-change full build without modifying either PR branch."""
import ast
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path.cwd()
AUDIT = ROOT / 'audit'
AUDIT.mkdir(exist_ok=True)
SOURCE = Path(os.environ['RUNNER_TEMP']) / 'combined-source'
SHA = '19c93459614359c7d94ab65b807606e40ffce71b'


def record(command, name, cwd=None):
    p = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, check=False)
    (AUDIT / name).write_text(p.stdout)
    assert p.returncode == 0, (command, p.stdout[-3000:])
    return p.stdout


record(['git', 'worktree', 'add', '--detach', str(SOURCE), SHA], 'checkout.log', ROOT)
record(['git', 'merge-base', '--is-ancestor', '55f21fa99021d3f4aed7e6472210e220a615bf5c', SHA],
       'shared-pr-ancestor.log', ROOT)
assert '15.3.0' in record(['riscv64-linux-gnu-g++', '-v'], 'gcc-version.log')
assert '22.1.8' in record(['clang++', '--version'], 'clang-version.log')
record(['python3', '--version'], 'python-version.log')
record(['rustc', '-vV'], 'rustc-version.log')
record(['cargo', '-V'], 'cargo-version.log')
record(['riscv64-linux-gnu-gcc', '-Q', '--help=target'], 'gcc-defaults.log')
record(['dpkg-query', '-W'], 'packages.log')
allowed = {'i', 'm', 'a', 'f', 'd', 'c', 'zicsr', 'zifencei', 'zmmul',
           'zaamo', 'zalrsc', 'zca', 'zcd'}
for name in ['libc.so.6', 'libstdc++.so.6', 'libm.so.6', 'libgcc_s.so.1']:
    path = record(['riscv64-linux-gnu-g++', '-print-file-name=' + name], name + '-path.log').strip()
    headers = record(['riscv64-linux-gnu-readelf', '-h', path], name + '-headers.log')
    assert 'RISC-V' in headers and 'double-float ABI' in headers
    attrs = record(['riscv64-linux-gnu-readelf', '-A', path], name + '-attributes.log')
    arches = re.findall(r'Tag_RISCV_arch: "([^"]+)"', attrs)
    assert arches, name
    for arch in arches:
        assert arch.startswith('rv64'), arch
        extensions = {re.sub(r'\d+p\d+$', '', part) for part in arch[4:].split('_')}
        assert extensions <= allowed, (name, arch)
p = SOURCE / 'deps/v8/src/heap/mutable-page.cc'
s = p.read_text()
needle = 'std::hardware_destructive_interference_size'
assert s.count(needle) == 2
p.write_text(s.replace(needle, '64'))
record(['git', 'diff', '--check'], 'patch-check.log', SOURCE)
record(['git', 'diff'], 'v8-candidate.patch', SOURCE)
(AUDIT / 'source-path.txt').write_text(str(SOURCE) + '\n')
(AUDIT / 'conditions.json').write_text(json.dumps({
    'source': SHA, 'shared_generation_pr': 66804, 'rust_pr': 66823,
    'v8_change': 'candidate /64 assertion only', 'jobs': 4,
    'target': 'rv64gc/lp64d', 'temporal': 'explicitly enabled; reporter setting unknown',
    'difference_from_reporter': 'PR source plus three fixes, -j4 instead of -j20; GHA resources differ',
}, indent=2))
# Ensure the environment variable is used only by the configure subprocess.
env = dict(os.environ, CARGO_BUILD_TARGET='riscv64gc-unknown-linux-gnu')
with (AUDIT / 'configure.log').open('w') as log:
    subprocess.run(['./configure', '--dest-cpu=riscv64', '--dest-os=linux', '--prefix=/usr',
                    '--cross-compiling', '--v8-enable-temporal-support'], cwd=SOURCE, env=env,
                   stdout=log, stderr=subprocess.STDOUT, check=True)
config = (SOURCE / 'config.gypi').read_text()
(AUDIT / 'config.gypi').write_text(config)
v = ast.literal_eval(config)['variables']
assert v['v8_enable_temporal_support'] == 1 and v['cargo_cross_compiling'] == 1
assert v['cargo_rust_target_target'] == 'riscv64gc-unknown-linux-gnu'
assert v['cargo_rust_target_host'] == 'x86_64-unknown-linux-gnu'
assert 'CARGO_BUILD_TARGET' not in os.environ
print('Source prepared; toolchain, sysroot ISA/ABI, and Temporal configuration verified.', flush=True)
