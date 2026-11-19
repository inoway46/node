"""Prepare and audit the RISC-V cross-build validation of nodejs/node#67070.

Fork-only validation helper; not for upstream.
"""
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
SOURCE = Path(os.environ.get('RUNNER_TEMP', '/tmp')) / 'riscv-v8-158-source'
# Head of nodejs/node#67070 (deps: update V8 to 15.8.62.44).
BASE = '2aaf14aeddb1995a2dbc304b3dd03cb8b6d87e80'
V8_VERSION = (15, 8, 62, 44)
VARIANT = os.environ.get('VARIANT', 'pr-head')
VARIANTS = ['pr-head', 'mutable-page-workaround']
OWN_PATHS = ('.github/workflows/riscv-v8-158.yml', 'tools/validation-riscv-v8-158/')
HIGHWAY_UNITS = ['json/json-parser', 'json/json-stringifier', 'objects/string',
                 'strings/string-hasher', 'runtime/runtime-regexp', 'strings/unicode']
MUTABLE_PAGE = 'deps/v8/src/heap/mutable-page.cc'
MUTABLE_PAGE_OLD = '''  static_assert(
      kOffsetOfFirstFastField / std::hardware_destructive_interference_size ==
      kOffsetOfLastFastField / std::hardware_destructive_interference_size);
'''
MUTABLE_PAGE_NEW = ('  static_assert(kOffsetOfFirstFastField / 64 == '
                    'kOffsetOfLastFastField / 64);\n')
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
    assert VARIANT in VARIANTS, VARIANT
    revision = record(['git', 'rev-parse', 'HEAD'], 'validation-sha.log', ROOT).strip()
    changed = record(['git', 'diff', '--name-only', BASE, revision],
                     'changed-since-base.log', ROOT).split()
    # The validation commit must add only the workflow and these helpers.
    assert changed and all(path.startswith(OWN_PATHS) for path in changed), changed
    record(['git', 'worktree', 'add', '--detach', str(SOURCE), revision], 'checkout.log', ROOT)
    version = (SOURCE / 'deps/v8/include/v8-version.h').read_text()
    found = tuple(int(re.search(rf'#define V8_{name} (\d+)', version).group(1))
                  for name in ['MAJOR_VERSION', 'MINOR_VERSION', 'BUILD_NUMBER', 'PATCH_LEVEL'])
    assert found == V8_VERSION, found
    # No fixed-width Highway tags may remain, and riscv64 must not force EMU128.
    tags = record(['git', 'grep', '-nE', r'hw::[A-Za-z]*Tag<', '--', 'deps/v8/src'],
                  'highway-tags.log', SOURCE)
    assert 'CappedTag' in tags and 'FixedTag' not in tags, tags
    highway_gyp = (SOURCE / 'tools/v8_gypfiles/highway.gyp').read_text()
    (AUDIT / 'highway.gyp').write_text(highway_gyp)
    emu128 = re.findall(r"\['([^']*)', \{\s*'defines': \['HWY_BROKEN_EMU128=0'", highway_gyp)
    assert emu128 and not any('riscv64' in condition for condition in emu128), emu128
    if VARIANT == 'mutable-page-workaround':
        path = SOURCE / MUTABLE_PAGE
        text = path.read_text()
        assert text.count(MUTABLE_PAGE_OLD) == 1, MUTABLE_PAGE
        path.write_text(text.replace(MUTABLE_PAGE_OLD, MUTABLE_PAGE_NEW))
    patch = record(['git', 'diff', '--binary'], 'applied.patch', SOURCE)
    assert bool(patch.strip()) == (VARIANT == 'mutable-page-workaround'), patch
    (AUDIT / 'source-path.txt').write_text(str(SOURCE) + '\n')
    (AUDIT / 'conditions.json').write_text(json.dumps({
        'base': BASE, 'base_description': 'head of nodejs/node#67070',
        'v8': '.'.join(map(str, V8_VERSION)),
        'validation_revision': revision, 'variant': VARIANT,
        'source_changes': ['MutablePage /64 workaround'] if patch.strip() else [],
        'gcc': '15.3.0', 'clang': '22.1.8', 'rust': '1.99.1',
        'target': 'rv64gc/lp64d', 'generator': 'make', 'jobs': 4, 'keep_going': True,
        'temporal': 'explicitly enabled',
        'qemu_cpu': QEMU_CPU,
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
    print(f'#67070 head configured with Temporal enabled (variant: {VARIANT}).', flush=True)


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
        'base': BASE, 'variant': VARIANT, 'full_build_link_install': 'passed',
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


def summary():
    """Write the per-variant result table to the job summary."""
    AUDIT.mkdir(exist_ok=True)
    exit_file = AUDIT / 'build-exit-code'
    build_exit = exit_file.read_text().strip() if exit_file.exists() else 'not run'
    log = AUDIT / 'build.log'
    lines = log.read_text(errors='replace').splitlines() if log.exists() else []
    errors = [line for line in lines if re.search(r':\d+(?::\d+)?: (?:fatal )?error:|collect2: error:', line)]
    files = {}
    for line in errors:
        match = re.match(r'(?:\.\./)*([^\s:]+):\d+', line)
        key = match.group(1) if match else '(other)'
        files[key] = files.get(key, 0) + 1
    (AUDIT / 'build-errors.log').write_text('\n'.join(errors) + '\n')
    rows = []
    for unit in HIGHWAY_UNITS:
        objects = list((SOURCE / 'out/Release/obj.target').glob(f'**/deps/v8/src/{unit}.o'))
        commands = [line for line in lines
                    if 'riscv64-linux-gnu-g++' in line and f'deps/v8/src/{unit}.cc' in line]
        forced = any('HWY_BROKEN_EMU128' in line for line in commands)
        unit_errors = sum(count for name, count in files.items()
                          if name.endswith(f'deps/v8/src/{unit}.cc'))
        rows.append((unit + '.cc', 'yes' if objects else 'NO', len(commands),
                     'yes' if forced else 'no', unit_errors))
    smoke_log = AUDIT / 'node-smoke.log'
    smoke_result = 'not run'
    if (AUDIT / 'success.json').exists():
        smoke_result = 'passed'
    elif smoke_log.exists():
        smoke_result = 'FAILED'
    out = [f'## riscv64 rv64gc cross-build of nodejs/node#67070 ({VARIANT})', '',
           f'- Base: `{BASE}` (V8 {".".join(map(str, V8_VERSION))})',
           '- Target compiler: GCC 15.3.0, `-march=rv64gc`, `make -k -j4`',
           f'- Build exit code: `{build_exit}`',
           f'- Compiler error lines: {len(errors)}',
           f'- QEMU smoke test (non-RVV): {smoke_result}', '',
           '### Highway translation units (target toolset)', '',
           '| File | Object built | Compile commands | HWY_BROKEN_EMU128 defined | Error lines |',
           '| --- | --- | --- | --- | --- |']
    out += ['| ' + ' | '.join(map(str, row)) + ' |' for row in rows]
    if files:
        out += ['', '### Error lines by file', '', '| File | Error lines |', '| --- | --- |']
        out += [f'| {name} | {count} |' for name, count in sorted(files.items())]
        out += ['', '### First error lines', '', '```'] + [e[:300] for e in errors[:15]] + ['```']
    text = '\n'.join(out) + '\n'
    (AUDIT / 'summary.md').write_text(text)
    target = os.environ.get('GITHUB_STEP_SUMMARY')
    if target:
        with open(target, 'a') as handle:
            handle.write(text)
    print(text, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['toolchain', 'prepare', 'save_binary', 'smoke', 'diagnostics', 'summary'])
    globals()[parser.parse_args().phase]()
