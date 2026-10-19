"""Prepare and audit the original-issue RISC-V cross-build validation."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
TOOLS = Path(__file__).resolve().parent
AUDIT = ROOT / 'audit-temporal'
SOURCE = Path(os.environ.get('RUNNER_TEMP', '/tmp')) / 'issue-66803-temporal-source'
BASE = 'f59539b514344ed0a0945f8790d61121df88a5d4'
QEMU_CPU = 'rv64,v=false,zba=false,zbb=false,zbc=false,zbs=false'
RUNTIME_LIBRARIES = ['libatomic.so.1', 'libstdc++.so.6', 'libgcc_s.so.1', 'libc.so.6', 'libm.so.6']
ALLOWED = {'i', 'm', 'a', 'f', 'd', 'c', 'zicsr', 'zifencei', 'zmmul',
           'zaamo', 'zalrsc', 'zca', 'zcd'}


def record(command, name, cwd=None, env=None, check=True, timeout=180):
    result = subprocess.run(command, cwd=cwd, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            check=False, timeout=timeout)
    (AUDIT / name).write_text(result.stdout)
    if check:
        assert result.returncode == 0, (command, result.stdout[-3000:])
    return result.stdout


def audit_elf(path, name, machine='RISC-V'):
    headers = record(['riscv64-linux-gnu-readelf', '-h', str(path)], name + '-headers.log')
    machines = re.findall(r'Machine:\s+(.+)', headers)
    assert machines and all(machine in value for value in machines), (path, machines)
    if machine != 'RISC-V':
        return
    attributes = record(['riscv64-linux-gnu-readelf', '-A', str(path)], name + '-attributes.log')
    arches = re.findall(r'Tag_RISCV_arch: "([^"]+)"', attributes)
    assert arches, path
    for arch in arches:
        assert arch.startswith('rv64'), arch
        extensions = {re.sub(r'\d+p\d+$', '', part) for part in arch[4:].split('_')}
        assert extensions <= ALLOWED, (path, arch)
    # Some archive members contain no floating-point code and omit the ABI flag.
    if Path(path).suffix != '.a':
        assert 'double-float ABI' in headers, path


def runtime_options(sysroot):
    libraries = json.loads((AUDIT / 'runtime-libraries.json').read_text())
    directories = list(dict.fromkeys(str(Path(path).parent) for path in libraries.values()))
    return ['-cpu', QEMU_CPU, '-L', sysroot,
            '-E', 'LD_LIBRARY_PATH=' + ':'.join(directories)]


def save_binary():
    candidates = [SOURCE / 'target/usr/bin/node', SOURCE / 'out/Release/node']
    node = next((path for path in candidates if path.is_file()), None)
    if node is None:
        return
    libraries = json.loads((AUDIT / 'runtime-libraries.json').read_text())
    sysroot = (AUDIT / 'sysroot.log').read_text().strip()
    manifest = {
        'node_source': str(node), 'sha256': hashlib.sha256(node.read_bytes()).hexdigest(),
        'runtime_libraries': libraries, 'qemu_cpu': QEMU_CPU,
        'example_command': 'qemu-riscv64-static -cpu ' + QEMU_CPU +
                           ' -L runtime -E LD_LIBRARY_PATH="$PWD/runtime/lib"'
                           ' ./node --harmony-temporal smoke.js',
    }
    (AUDIT / 'node-bundle.json').write_text(json.dumps(manifest, indent=2) + '\n')
    with tarfile.open(AUDIT / 'node-runtime.tar.gz', 'w:gz') as archive:
        archive.add(node, arcname='node')
        archive.add(TOOLS / 'smoke.js', arcname='smoke.js')
        archive.add(AUDIT / 'node-bundle.json', arcname='node-bundle.json')
        archive.add(AUDIT / 'config.gypi', arcname='config.gypi')
        for name, path in libraries.items():
            archive.add(path, arcname='runtime/lib/' + name)
        archive.add(Path(sysroot) / 'lib/ld-linux-riscv64-lp64d.so.1',
                    arcname='runtime/lib/ld-linux-riscv64-lp64d.so.1')
    print('Saved Node, runtime libraries and smoke script before QEMU execution.', flush=True)


def toolchain():
    AUDIT.mkdir(exist_ok=True)
    assert '15.3.0' in record(['riscv64-linux-gnu-g++', '-v'], 'gcc-version.log')
    assert '22.1.8' in record(['clang++', '--version'], 'clang-version.log')
    for command, name in [(['rustc', '-vV'], 'rustc-version.log'),
                          (['cargo', '-V'], 'cargo-version.log'),
                          (['python3', '--version'], 'python-version.log'),
                          (['qemu-riscv64-static', '--version'], 'qemu-version.log'),
                          (['dpkg-query', '-W'], 'packages.log')]:
        record(command, name)
    defaults = record(['riscv64-linux-gnu-gcc', '-Q', '--help=target'], 'gcc-defaults.log')
    assert re.search(r'-mabi=\s+lp64d(?:\s|$)', defaults), defaults
    sysroot = record(['riscv64-linux-gnu-gcc', '-print-sysroot'], 'sysroot.log').strip()
    assert Path(sysroot).is_dir(), sysroot
    libraries = {}
    for library in RUNTIME_LIBRARIES:
        path = record(['riscv64-linux-gnu-g++', '-print-file-name=' + library],
                      library + '-path.log').strip()
        path = Path(path).resolve(strict=True)
        audit_elf(path, library)
        libraries[library] = str(path)
    (AUDIT / 'runtime-libraries.json').write_text(json.dumps(libraries, indent=2) + '\n')
    audit_elf(Path(sysroot) / 'lib/ld-linux-riscv64-lp64d.so.1', 'loader')
    for tool in ['ar', 'ranlib', 'ld', 'readelf']:
        record(['riscv64-linux-gnu-' + tool, '--version'], tool + '-version.log')
    (AUDIT / 'probe.c').write_text('int answer(void) { return 42; }\n')
    (AUDIT / 'main.c').write_text('int answer(void); int main(void) { return answer() != 42; }\n')
    record(['riscv64-linux-gnu-gcc', '-march=rv64gc', '-mabi=lp64d', '-c',
            str(AUDIT / 'probe.c'), '-o', str(AUDIT / 'probe.o')], 'probe-compile.log')
    record(['riscv64-linux-gnu-ar', 'rcs', str(AUDIT / 'probe.a'),
            str(AUDIT / 'probe.o')], 'probe-ar.log')
    record(['riscv64-linux-gnu-ranlib', str(AUDIT / 'probe.a')], 'probe-ranlib.log')
    record(['riscv64-linux-gnu-gcc', '-march=rv64gc', '-mabi=lp64d',
            str(AUDIT / 'main.c'), str(AUDIT / 'probe.a'),
            '-Wl,--no-as-needed', '-latomic', '-lstdc++', '-o', str(AUDIT / 'probe')],
           'probe-link.log')
    audit_elf(AUDIT / 'probe', 'probe')
    record(['riscv64-linux-gnu-readelf', '-d', str(AUDIT / 'probe')], 'probe-dynamic.log')
    record(['qemu-riscv64-static'] + runtime_options(sysroot) +
           [str(AUDIT / 'probe')], 'probe-qemu.log')
    print('Toolchain, ar/libfl, sysroot ISA/ABI, and non-RVV QEMU preflight passed.', flush=True)


def prepare():
    AUDIT.mkdir(exist_ok=True)
    record(['git', 'worktree', 'add', '--detach', str(SOURCE), BASE], 'checkout.log', ROOT)
    for patch in ['66804.patch', '66823.patch', 'v8-candidates.patch']:
        path = TOOLS / 'patches' / patch
        record(['git', 'apply', '--check', str(path)], patch + '-check.log', SOURCE)
        record(['git', 'apply', str(path)], patch + '-apply.log', SOURCE)
    record(['git', 'diff', '--check'], 'diff-check.log', SOURCE)
    record(['git', 'diff', '--binary'], 'applied.patch', SOURCE)
    (AUDIT / 'source-path.txt').write_text(str(SOURCE) + '\n')
    (AUDIT / 'conditions.json').write_text(json.dumps({
        'base': BASE,
        'shared_pr_head': '55f21fa99021d3f4aed7e6472210e220a615bf5c',
        'rust_pr_head': '19c93459614359c7d94ab65b807606e40ffce71b',
        'fixes': ['66804', '66823', 'MutablePage /64 candidate', 'four CappedTag uses'],
        'gcc': '15.3.0', 'clang': '22.1.8', 'rust': '1.99.1',
        'target': 'rv64gc/lp64d', 'generator': 'make', 'jobs': 4,
        'temporal': 'explicitly enabled; original reporter setting unknown',
        'qemu_cpu': QEMU_CPU,
        'differences_from_reporter': ['four proposed fixes', '-j4 instead of -j20',
                                      'explicit Rust target and Temporal; reporter settings unknown',
                                      'GHA resources and container snapshot'],
    }, indent=2) + '\n')
    env = dict(os.environ, CARGO_BUILD_TARGET='riscv64gc-unknown-linux-gnu')
    record(['./configure', '--dest-cpu=riscv64', '--dest-os=linux', '--prefix=/usr',
            '--cross-compiling', '--v8-enable-temporal-support'], 'configure.log', SOURCE, env)
    config = (SOURCE / 'config.gypi').read_text()
    (AUDIT / 'config.gypi').write_text(config)
    variables = ast.literal_eval(config)['variables']
    assert variables['target_arch'] == 'riscv64'
    assert variables['v8_enable_temporal_support'] == 1
    assert variables['cargo_cross_compiling'] == 1
    assert variables['cargo_rust_target_target'] == 'riscv64gc-unknown-linux-gnu'
    assert variables['cargo_rust_target_host'] == 'x86_64-unknown-linux-gnu'
    assert 'CARGO_BUILD_TARGET' not in os.environ
    print('Original issue source plus four fixes configured with Temporal enabled.', flush=True)


def smoke():
    node = SOURCE / 'target/usr/bin/node'
    assert node.is_file(), node
    audit_elf(node, 'installed-node')
    out_node = SOURCE / 'out/Release/node'
    assert hashlib.sha256(node.read_bytes()).digest() == hashlib.sha256(out_node.read_bytes()).digest()
    sysroot = (AUDIT / 'sysroot.log').read_text().strip()
    record(['riscv64-linux-gnu-readelf', '-d', str(node)], 'installed-node-dynamic.log')
    command = ['qemu-riscv64-static'] + runtime_options(sysroot) + [str(node)]
    (AUDIT / 'qemu-command.json').write_text(json.dumps(command, indent=2) + '\n')
    record(command + ['--version'], 'node-version.log')
    result = record(command + ['--harmony-temporal', str(TOOLS / 'smoke.js')],
                    'node-smoke.log', timeout=300)
    print(result, flush=True)
    (AUDIT / 'success.json').write_text(json.dumps({
        'base': BASE, 'full_build_link_install': 'passed',
        'qemu_basic_runtime_and_temporal': 'passed', 'full_test_suite': False,
        'target': 'rv64gc/lp64d', 'temporal': True,
    }, indent=2) + '\n')


def diagnostics():
    AUDIT.mkdir(exist_ok=True)
    if SOURCE.exists():
        (AUDIT / 'install-files.log').write_text('\n'.join(
            str(path.relative_to(SOURCE)) for path in (SOURCE / 'target').rglob('*')) + '\n')
        for toolset, triple, machine in [
            ('host', 'x86_64-unknown-linux-gnu', 'Advanced Micro Devices X86-64'),
            ('target', 'riscv64gc-unknown-linux-gnu', 'RISC-V')]:
            archives = list((SOURCE / 'out').glob(
                f'**/cargo/{toolset}/{triple}/release/libnode_crates.a'))
            (AUDIT / f'{toolset}-rust-paths.log').write_text('\n'.join(map(str, archives)) + '\n')
            build_exit = AUDIT / 'build-exit-code'
            if build_exit.exists() and build_exit.read_text().strip() == '0':
                assert archives, f'Missing {toolset} Rust archive'
            if archives:
                for index, archive in enumerate(archives):
                    audit_elf(archive, f'rust-{toolset}-{index}', machine)
        record(['git', 'diff', '--binary'], 'final-applied.patch', SOURCE)
    print('Diagnostics saved.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['toolchain', 'prepare', 'save_binary', 'smoke', 'diagnostics'])
    globals()[parser.parse_args().phase]()
