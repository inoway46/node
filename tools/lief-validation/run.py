#!/usr/bin/env python3
"""Build and exercise a fixed Node/LIEF input independently of the workflow branch."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile


VERSIONS = {
    '0.17.0': {
        'commit': '038b60671f12dbd86bf84d9f8a38395bd2a8176e',
        'sha256': 'b2aee837b27627efbef171f58c6e529aea94e1791cc1e5a37aa5770e05dd0cb5',
    },
    '1.0.0': {
        'commit': 'd05b3499b6934137e917c009a4df0a9dc8cb11c5',
        'sha256': 'dc70a7d42feb989266c66e6b42c874ada5c40ec29f2c18a3eb146bf56219a1ea',
    },
}
FEATURES = {
    'LIEF_USE_CCACHE': 'OFF', 'LIEF_INSTALL': 'ON',
    'LIEF_TESTS': 'OFF', 'LIEF_EXAMPLES': 'OFF', 'LIEF_C_API': 'OFF',
    'LIEF_PYTHON_API': 'OFF', 'LIEF_RUST_API': 'OFF',
    'LIEF_ELF': 'ON', 'LIEF_PE': 'ON', 'LIEF_MACHO': 'ON', 'LIEF_COFF': 'ON',
    'LIEF_DEX': 'OFF', 'LIEF_ART': 'OFF', 'LIEF_OAT': 'OFF', 'LIEF_VDEX': 'OFF',
    'LIEF_ENABLE_JSON': 'OFF', 'LIEF_LOGGING': 'OFF', 'LIEF_LOGGING_DEBUG': 'OFF',
    'LIEF_DEBUG_INFO': 'OFF', 'LIEF_OBJC': 'OFF', 'LIEF_DYLD_SHARED_CACHE': 'OFF',
    'LIEF_ASM': 'OFF', 'LIEF_DISABLE_FROZEN': 'OFF', 'LIEF_DISABLE_EXCEPTIONS': 'ON',
}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def manifest(root):
    return {p.relative_to(root).as_posix(): digest(p)
            for p in sorted(root.rglob('*')) if p.is_file()}


class Runner:
    def __init__(self, results):
        self.results = results
        results.mkdir(parents=True, exist_ok=True)

    def run(self, label, args, cwd, *, env=None, check=True):
        command = [str(arg) for arg in args]
        print(f'::group::{label}\n{shlex.join(command)}', flush=True)
        started = time.monotonic()
        with (self.results / f'{label}.log').open('w', encoding='utf-8') as log:
            proc = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
            for line in proc.stdout:
                log.write(line)
                print(line, end='', flush=True)
            proc.wait()
        with (self.results / 'commands.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'label': label, 'command': command, 'cwd': str(cwd),
                                     'exit_code': proc.returncode,
                                     'seconds': round(time.monotonic() - started, 2)}) + '\n')
        print('::endgroup::', flush=True)
        output = (self.results / f'{label}.log').read_text(encoding='utf-8')
        if check and proc.returncode:
            raise RuntimeError(f'{label} failed with exit code {proc.returncode}')
        return proc.returncode, output


def capture(args, cwd):
    return subprocess.check_output([str(a) for a in args], cwd=cwd, text=True).strip()


def archive_manifest(path):
    result = {}
    with tarfile.open(path, 'r:gz') as archive:
        for entry in archive:
            if entry.name.startswith('deps/LIEF/') and entry.isfile():
                result[entry.name.removeprefix('deps/LIEF/')] = hashlib.sha256(archive.extractfile(entry).read()).hexdigest()
    return result


def extract_tar(path, destination):
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(path, 'r:gz') as archive:
        if sys.platform == 'win32':
            # Match Git for Windows core.symlinks=false for unrelated fixture links.
            links = [entry for entry in archive.getmembers() if entry.issym()]
            regular = [entry for entry in archive.getmembers() if not entry.issym()]
            archive.extractall(destination, members=regular, filter='data')
            for entry in links:
                target = destination / entry.name
                if not target.resolve().is_relative_to(destination.resolve()):
                    raise RuntimeError(f'Unsafe tar path: {entry.name}')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(entry.linkname, encoding='utf-8')
        else:
            archive.extractall(destination, filter='data')


def get_upstream(version, output, archive_dir=None):
    archive = output / f'LIEF-{version}.zip'
    if archive_dir:
        shutil.copy2(archive_dir / archive.name, archive)
    else:
        request = urllib.request.Request(
            f'https://github.com/lief-project/LIEF/archive/refs/tags/{version}.zip',
            headers={'User-Agent': 'node-lief-validation'})
        with urllib.request.urlopen(request, timeout=120) as response, archive.open('wb') as stream:
            shutil.copyfileobj(response, stream)
    if digest(archive) != VERSIONS[version]['sha256']:
        raise RuntimeError(f'Unexpected archive SHA-256 for LIEF {version}')
    with zipfile.ZipFile(archive) as source:
        if source.comment.decode() != VERSIONS[version]['commit']:
            raise RuntimeError(f'Unexpected archive revision for LIEF {version}')
        source.extractall(output / 'upstream')
    return output / 'upstream' / f'LIEF-{version}'


def prepare(args):
    source, output = args.source.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    runner = Runner(output / 'prepare-results')
    if capture(['git', 'status', '--porcelain'], source):
        raise RuntimeError('Preparation requires a clean, isolated Node checkout')
    revision = capture(['git', 'rev-parse', 'HEAD'], source)
    baseline = manifest(source / 'deps/LIEF')
    if not re.search(r'#define LIEF_VERSION "0\.17\.0-', (source / 'deps/LIEF/include/LIEF/version.h').read_text()):
        raise RuntimeError('The Node revision must still bundle LIEF 0.17.0')
    runner.run('archive-baseline', ['git', 'archive', '--format=tar.gz', '-o', output / 'node-0.17.0.tar.gz', revision], source)
    if archive_manifest(output / 'node-0.17.0.tar.gz') != baseline:
        raise RuntimeError('Baseline vendor differs from the Git archive')
    upstream = {v: get_upstream(v, output, args.archive_dir) for v in VERSIONS}
    retained = {p.name: p.read_bytes() for p in (source / 'deps/LIEF').glob('*.gyp')}
    if args.use_updater:
        env = os.environ.copy()
        env['NODE'] = shutil.which('node') or ''
        if not env['NODE']:
            raise RuntimeError('A bootstrap Node is required for update-lief.sh')
        runner.run('update-lief', ['sh', 'tools/dep_updaters/update-lief.sh'], source, env=env)
    else:
        shutil.rmtree(source / 'deps/LIEF')
        runner.run('prepare-pinned-vendor', [sys.executable, 'tools/prepare_lief.py', '--source-dir', upstream['1.0.0'],
                                           '--lief-dir', source / 'deps/LIEF', '--version', '1.0.0'], source)
        for name, contents in retained.items():
            (source / 'deps/LIEF' / name).write_bytes(contents)
    header = (source / 'deps/LIEF/include/LIEF/version.h').read_text()
    if not re.search(r'#define LIEF_VERSION "1\.0\.0-', header):
        raise RuntimeError('Updater did not produce 1.0.0. Use the pinned preparation option if latest has advanced.')
    for name, contents in retained.items():
        if (source / 'deps/LIEF' / name).read_bytes() != contents:
            raise RuntimeError(f'Updater changed maintained build file {name}')
    reproduced = output / 'reproduced-vendor'
    runner.run('reproduce-vendor', [sys.executable, 'tools/prepare_lief.py', '--source-dir', upstream['1.0.0'],
                                  '--lief-dir', reproduced, '--version', '1.0.0'], source)
    vendor = manifest(source / 'deps/LIEF')
    if {p: h for p, h in vendor.items() if p not in retained} != manifest(reproduced):
        raise RuntimeError('Updater vendor differs from the pinned, reproducible preparation')
    runner.run('stage-vendor', ['git', 'add', '-A', '--', 'deps/LIEF'], source)
    _, staged = runner.run('staged-vendor-diff', ['git', 'diff', '--cached', '--stat', '--', 'deps/LIEF'], source)
    tree = capture(['git', 'write-tree'], source)
    runner.run('archive-updated-tree', ['git', 'archive', '--format=tar.gz', '-o', output / 'node-1.0.0.tar.gz', tree], source)
    if archive_manifest(output / 'node-1.0.0.tar.gz') != vendor:
        raise RuntimeError('Generated files or licenses are missing/changed in the staged Git archive')
    required = ['LICENSE', 'include/LIEF/config.h', 'include/LIEF/version.h', 'src/compiler_support.h',
                'third-party/mbedtls/tf-psa-crypto/LICENSE']
    for name in required:
        if name not in vendor:
            raise RuntimeError(f'Missing vendor file: {name}')
    write_json(output / 'inputs.json', {
        'node_revision': revision, 'prepared_tree': tree, 'updater_executed': args.use_updater,
        'vendor_source': 'updater' if args.use_updater else 'pinned',
        'lief_upstream': VERSIONS, 'vendor': {'0.17.0': baseline, '1.0.0': vendor},
        'archive_sha256': {p.name: digest(p) for p in output.glob('*.tar.gz')},
        'packaging': 'git add -A deps/LIEF; git write-tree; git archive (no commit)',
        'staged_diff': staged,
    })
    write_json(output / 'prepare-results' / 'result.json', {
        'node_revision': revision, 'status': 'passed', 'updater_executed': args.use_updater,
        'vendor_source': 'updater' if args.use_updater else 'pinned',
        'vendor_files': len(vendor), 'tarball_vendor_identical': True,
    })
    with Path(os.environ.get('GITHUB_OUTPUT', output / 'outputs.txt')).open('a') as stream:
        stream.write(f'node_sha={revision}\n')


def prepare_checked_in(args):
    source, output = args.source.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    runner = Runner(output / 'prepare-results')
    if capture(['git', 'status', '--porcelain'], source):
        raise RuntimeError('Preparation requires a clean, isolated Node checkout')
    header = (source / 'deps/LIEF/include/LIEF/version.h').read_text()
    if not re.search(r'#define LIEF_VERSION "1\.0\.0-', header):
        raise RuntimeError('Checked-in mode requires the selected Node revision to bundle LIEF 1.0.0')
    revision = capture(['git', 'rev-parse', 'HEAD'], source)
    vendor = manifest(source / 'deps/LIEF')
    for name in ['LICENSE', 'include/LIEF/config.h', 'src/compiler_support.h',
                 'third-party/mbedtls/tf-psa-crypto/LICENSE']:
        if name not in vendor:
            raise RuntimeError(f'Missing vendor file: {name}')
    archive = output / 'node-1.0.0.tar.gz'
    runner.run('archive-checked-in-vendor', ['git', 'archive', '--format=tar.gz', '-o', archive, revision], source)
    if archive_manifest(archive) != vendor:
        raise RuntimeError('Checked-in vendor differs from the Git archive')
    write_json(output / 'inputs.json', {
        'node_revision': revision, 'prepared_tree': capture(['git', 'rev-parse', 'HEAD^{tree}'], source),
        'vendor_source': 'checked-in', 'updater_executed': False, 'vendor': {'1.0.0': vendor},
        'archive_sha256': {archive.name: digest(archive)}, 'packaging': 'git archive HEAD (no vendor changes)',
    })
    write_json(output / 'prepare-results' / 'result.json', {
        'node_revision': revision, 'status': 'passed', 'updater_executed': False,
        'vendor_source': 'checked-in', 'vendor_files': len(vendor), 'tarball_vendor_identical': True,
    })
    with Path(os.environ.get('GITHUB_OUTPUT', output / 'outputs.txt')).open('a') as stream:
        stream.write(f'node_sha={revision}\n')


def matrix():
    is_push = os.environ.get('GITHUB_EVENT_NAME') == 'push'
    enabled = lambda name: is_push or os.environ.get(name, 'true') == 'true'
    rows = []
    if enabled('WANT_WINDOWS'):
        variants = ['bundled-0.17.0', 'bundled-1.0.0', 'shared-1.0.0']
        if enabled('WANT_OLD'):
            variants.append('shared-0.17.0')
        rows += [{'name': f'windows-x64-{v}', 'runner': 'windows-2022', 'variant': v,
                  'arch': 'x64', 'jobs': 4, 'execute_sea': True} for v in variants]
    if enabled('WANT_MACOS'):
        rows += [
            {'name': 'macos-arm64-shared-1.0.0', 'runner': 'macos-15', 'variant': 'shared-1.0.0',
             'arch': 'arm64', 'jobs': 2, 'execute_sea': True},
            {'name': 'macos-x64-shared-1.0.0', 'runner': 'macos-15-intel', 'variant': 'shared-1.0.0',
             'arch': 'x64', 'jobs': 3, 'execute_sea': os.environ.get('EXECUTE_MAC_X64_SEA') == 'true'},
        ]
    if not rows:
        raise RuntimeError('Enable at least one platform')
    print(json.dumps(rows, indent=2))
    with Path(os.environ['GITHUB_OUTPUT']).open('a') as stream:
        stream.write(f'matrix={json.dumps({"include": rows}, separators=(",", ":"))}\n')


def unpack(args):
    work, inputs = args.work.resolve(), args.inputs.resolve()
    work.mkdir(parents=True, exist_ok=False)
    metadata = json.loads((inputs / 'inputs.json').read_text())
    version = args.variant.split('-', 1)[1]
    bundled = args.variant.startswith('bundled-')
    vendor_version = version if bundled else '0.17.0'
    archive = inputs / f'node-{vendor_version}.tar.gz'
    if digest(archive) != metadata['archive_sha256'][archive.name]:
        raise RuntimeError('Node input tarball checksum mismatch')
    extract_tar(archive, work / 'node')
    if manifest(work / 'node/deps/LIEF') != metadata['vendor'][vendor_version]:
        raise RuntimeError('Extracted vendor does not match the staged source manifest')
    observed_arch = {'AMD64': 'x64', 'x86_64': 'x64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(platform.machine())
    if observed_arch != args.arch:
        raise RuntimeError(f'Runner architecture is {observed_arch}, expected {args.arch}')
    if not bundled:
        upstream = get_upstream(version, work, inputs)
        metadata['upstream_source'] = str(upstream)
    metadata.update({'variant': args.variant, 'version': version, 'bundled': bundled,
                     'arch': observed_arch, 'platform': sys.platform, 'work': str(work),
                     'runner_image': os.environ.get('ImageVersion'),
                     'workflow_revision': os.environ.get('GITHUB_SHA')})
    write_json(work / 'state.json', metadata)
    write_json(args.results.resolve() / 'provenance.json', metadata)


def state(args):
    work = args.work.resolve()
    data = json.loads((work / 'state.json').read_text())
    return work, work / 'node', data, Runner(args.results.resolve())


def external(args):
    work, node, data, runner = state(args)
    if data['bundled']:
        return
    source = Path(data['upstream_source'])
    prefix, build = work / 'lief-install', work / 'lief-build'
    query = build / '.cmake/api/v1/query'
    query.mkdir(parents=True)
    (query / 'codemodel-v2').touch()
    options = FEATURES.copy()
    if data['version'] == '1.0.0':
        options['LIEF_RUNTIME'] = 'OFF'
    compiler_options = []
    if sys.platform == 'win32':
        compiler = Path(os.environ['VS_INSTALL']) / 'VC/Tools/Llvm/x64/bin/clang-cl.exe'
        compiler_options = [f'-DCMAKE_C_COMPILER={compiler}', f'-DCMAKE_CXX_COMPILER={compiler}',
                            '-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded']
    elif sys.platform == 'darwin':
        compiler_options = ['-DCMAKE_C_COMPILER=/usr/bin/clang', '-DCMAKE_CXX_COMPILER=/usr/bin/clang++',
                            f'-DCMAKE_OSX_ARCHITECTURES={"x86_64" if data["arch"] == "x64" else "arm64"}',
                            f'-DCMAKE_INSTALL_NAME_DIR={prefix / "lib"}']
    command = ['cmake', '-S', source, '-B', build, '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release',
               '-DBUILD_SHARED_LIBS=ON', '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',
               '-DCMAKE_DISABLE_PRECOMPILE_HEADERS=ON', f'-DCMAKE_INSTALL_PREFIX={prefix}',
               *compiler_options, *[f'-D{k}={v}' for k, v in options.items()]]
    try:
        runner.run('lief-configure', command, node)
        runner.run('lief-build', ['cmake', '--build', build, '--parallel', args.jobs], node)
        runner.run('lief-install', ['cmake', '--install', build], node)
    finally:
        for name in ['CMakeCache.txt', 'compile_commands.json']:
            if (build / name).exists():
                shutil.copy2(build / name, runner.results / name)
        if (build / '.cmake/api/v1/reply').exists():
            shutil.copytree(build / '.cmake/api/v1/reply', runner.results / 'cmake-file-api', dirs_exist_ok=True)
    installed = manifest(prefix)
    if not (prefix / 'include/LIEF/version.h').exists():
        raise RuntimeError('LIEF installed header is missing')
    write_json(runner.results / 'installed-lief.json', installed)


def configure(args):
    work, node, data, runner = state(args)
    flags = ['--dest-cpu', data['arch']]
    if sys.platform == 'win32':
        _, output = runner.run('compiler-version', ['clang-cl', '--version'], node)
        version = re.search(r'(?:clang version|LLVM version) ([\d.]+)', output)
        if not version:
            raise RuntimeError('Cannot determine Visual Studio clang-cl version')
        flags += [f'--clang-cl={version[1]}']
        os.environ['GYP_MSVS_VERSION'] = '2022'
    else:
        compiler = shlex.split(os.environ.get('CXX', 'c++' if sys.platform == 'linux' else '/usr/bin/clang++'))
        runner.run('compiler-version', [*compiler, '--version'], node)
    runner.run('rust-version', ['rustc', '--version'], node)
    if not data['bundled']:
        prefix = work / 'lief-install'
        flags += ['--shared-lief', '--shared-lief-includes', prefix / 'include',
                  '--shared-lief-libpath', prefix / 'lib', '--shared-lief-libname', 'LIEF']
    runner.run('node-configure', [sys.executable, 'configure.py', *flags], node)
    for name in ['config.gypi', 'config.mk', 'config.status']:
        shutil.copy2(node / name, runner.results / name)
    if sys.platform == 'win32':
        node_projects = []
        for path in node.rglob('*.vcxproj'):
            if path.name in ('node.vcxproj', 'liblief.vcxproj'):
                destination = runner.results / 'projects' / path.relative_to(node)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
                if path.name == 'node.vcxproj':
                    node_projects.append(path)
        if data['bundled'] and data['version'] == '1.0.0':
            if not any(re.search(r'\bbcrypt\.lib\b', p.read_text(encoding='utf-8'), re.IGNORECASE) for p in node_projects):
                raise RuntimeError('The generated Node linker project is missing bcrypt.lib')


def build_node(args):
    work, node, data, runner = state(args)
    if sys.platform == 'win32':
        command = ['msbuild', 'node.sln', '/t:node', f'/m:{args.jobs}', '/p:Configuration=Release',
                   '/p:Platform=x64', '/nologo', '/clp:NoItemAndPropertyList;Verbosity=minimal']
        env = os.environ.copy()
        env.update({'UseMultiToolTask': 'True', 'EnforceProcessCountAcrossBuilds': 'True',
                    'MultiProcMaxCount': str(args.jobs)})
        runner.run('node-build', command, node, env=env)
    else:
        runner.run('node-build', ['make', f'-j{args.jobs}', 'V=1'], node)
    binary = node / 'out/Release' / ('node.exe' if sys.platform == 'win32' else 'node')
    if not binary.exists():
        raise RuntimeError(f'Node output is missing: {binary}')
    if not data['bundled'] and sys.platform == 'win32':
        dlls = list((work / 'lief-install/lib').glob('*.dll'))
        if not dlls:
            raise RuntimeError('The external LIEF DLL is missing')
        for dll in dlls:
            shutil.copy2(dll, binary.parent / dll.name)
    write_json(runner.results / 'node-binary.json', {'path': str(binary), 'sha256': digest(binary), 'bytes': binary.stat().st_size})


def debug_lief(args):
    _, node, data, runner = state(args)
    if sys.platform != 'win32' or not data['bundled']:
        return
    runner.run('lief-debug-build', ['msbuild', 'node.sln', '/t:liblief', f'/m:{args.jobs}',
                                  '/p:Configuration=Debug', '/p:Platform=x64', '/nologo',
                                  '/clp:NoItemAndPropertyList;Verbosity=minimal'], node)
    archives = [p for p in (node / 'out/Debug').rglob('*.lib') if 'lief' in p.name.lower()]
    if not archives:
        raise RuntimeError('The Debug LIEF archive is missing')
    write_json(runner.results / 'lief-debug-archives.json', {str(p.relative_to(node)): digest(p) for p in archives})


def runtime_env(work, data):
    env = os.environ.copy()
    if not data['bundled']:
        lib = str(work / 'lief-install/lib')
        env['PATH'] = lib + os.pathsep + env['PATH']
        if sys.platform == 'darwin':
            env['DYLD_LIBRARY_PATH'] = lib
    return env


def inspect_dependencies(binary, label, node, data, runner, env):
    tool = {'win32': ['dumpbin', '/DEPENDENTS'], 'darwin': ['otool', '-L'],
            'linux': ['readelf', '--dynamic']}[sys.platform]
    _, output = runner.run(label, [*tool, binary], node, env=env)
    dynamic_lief = re.search(r'(?:lib)?LIEF[^\s]*(?:\.dll|\.dylib|\.so(?:\.\d+)*)', output, re.IGNORECASE) is not None
    if dynamic_lief == data['bundled']:
        raise RuntimeError(f'{label}: bundled/shared LIEF linkage does not match the selected mode')


def smoke(work, node, data, runner, env, execute):
    smoke_dir = work / 'sea-smoke'
    smoke_dir.mkdir()
    (smoke_dir / 'main.js').write_text(
        "const assert = require('node:assert/strict');\n"
        "const sea = require('node:sea');\n"
        "assert.ok(sea.isSea());\n"
        "assert.equal(sea.getAsset('payload', 'utf8'), 'LIEF SEA asset 😊\\n');\n"
        f"assert.ok(process.versions.lief.startsWith('{data['version']}'));\n"
        "console.log('lief-sea-smoke-ok');\n", encoding='utf-8')
    (smoke_dir / 'payload.txt').write_text('LIEF SEA asset 😊\n', encoding='utf-8')
    executable = smoke_dir / ('sea.exe' if sys.platform == 'win32' else 'sea')
    write_json(smoke_dir / 'sea-config.json', {
        'main': 'main.js', 'output': executable.name, 'assets': {'payload': 'payload.txt'},
        'disableExperimentalSEAWarning': True,
    })
    binary = node / 'out/Release' / ('node.exe' if sys.platform == 'win32' else 'node')
    runner.run('sea-smoke-generate', [binary, '--build-sea', 'sea-config.json'], smoke_dir, env=env)
    if not executable.is_file():
        raise RuntimeError('SEA generation did not produce an executable')
    if sys.platform == 'darwin':
        runner.run('sea-smoke-sign', ['codesign', '--force', '--sign', '-', executable], node, env=env)
        runner.run('sea-smoke-verify-signature', ['codesign', '--verify', executable], node, env=env)
    elif sys.platform == 'win32':
        runner.run('sea-smoke-sign', ['signtool', 'sign', '/fd', 'SHA256', executable], node, env=env)
        runner.run('sea-smoke-verify-signature', ['signtool', 'verify', '/pa', '/v', executable], node, env=env)
    inspect_dependencies(executable, 'sea-dependencies', node, data, runner, env)
    if not data['bundled'] and sys.platform == 'win32':
        for dll in (work / 'lief-install/lib').glob('*.dll'):
            shutil.copy2(dll, smoke_dir / dll.name)
    if execute:
        _, output = runner.run('sea-smoke-execute', [executable], smoke_dir, env=env)
        if output.strip() != 'lief-sea-smoke-ok':
            raise RuntimeError('The generated SEA did not run the expected payload')
    return {'generated': True, 'execution': 'passed' if execute else 'not-run-macos-x64-known-issue-59553',
            'sha256': digest(executable)}


def test(args):
    work, node, data, runner = state(args)
    env = runtime_env(work, data)
    binary = node / 'out/Release' / ('node.exe' if sys.platform == 'win32' else 'node')
    _, output = runner.run('node-runtime', [binary, '-p',
        'JSON.stringify({versions:process.versions,arch:process.arch,platform:process.platform,config:process.config.variables})'], node, env=env)
    runtime = json.loads(output)
    write_json(runner.results / 'runtime.json', runtime)
    config = runtime['config']
    if not runtime['versions'].get('lief', '').startswith(data['version']):
        raise RuntimeError('The runtime LIEF version is not the selected version')
    if runtime['arch'] != data['arch'] or bool(config['node_shared_lief']) == data['bundled']:
        raise RuntimeError('Runtime architecture or external LIEF selection is wrong')
    if not config['node_use_lief'] or not config['single_executable_application']:
        raise RuntimeError('LIEF or SEA support was disabled')
    inspect_dependencies(binary, 'node-dependencies', node, data, runner, env)
    smoke_result = smoke(work, node, data, runner, env, args.execute_sea)
    write_json(runner.results / 'sea-smoke.json', smoke_result)
    failures = []
    if args.execute_sea:
        for name in ['test-single-executable-application', 'test-single-executable-application-assets']:
            code, output = runner.run(name, [binary, f'test/sea/{name}.js'], node, env=env, check=False)
            if code or re.search(r'#\s*SKIP\S*', output, re.IGNORECASE):
                failures.append(name)
    suite_command = [sys.executable, 'tools/test.py', '--shell', binary, '-j1', '-p', 'tap', '--report',
                     '--logfile', runner.results / 'sea-tests.tap', 'sea',
                     'parallel/test-sea-assets-not-in-sea',
                     'parallel/test-sea-get-asset-keys']
    code, output = runner.run('sea-suite', suite_command, node, env=env, check=False)
    if code:
        failures.append('sea-suite')
    lines = (runner.results / 'sea-tests.tap').read_text(encoding='utf-8').splitlines()
    result = {'node_revision': data['node_revision'], 'variant': data['variant'],
              'platform': data['platform'], 'arch': data['arch'], 'sea_smoke': smoke_result,
              'required_end_to_end_tests': 'passed' if args.execute_sea and not failures else 'not-validated',
              'tap_passed': sum(bool(re.match(r'^ok \d+ ', line)) and '# skip' not in line.lower() for line in lines),
              'tap_skipped': [line for line in lines if '# skip' in line.lower()],
              'status_file': (node / 'test/sea/sea.status').read_text(encoding='utf-8'),
              'status': 'failed' if failures else ('passed' if args.execute_sea else 'build-and-generation-only'),
              'failed_tests': failures,
              'note': 'macOS x64 status-file exclusions remain in effect; no workaround or test edits are applied.'}
    write_json(runner.results / 'result.json', result)
    if failures:
        raise RuntimeError(f'Test failures or unexpected skips: {failures}')


def summary(args):
    directory = args.results.resolve()
    result_file = directory / 'result.json'
    if result_file.exists():
        result = json.loads(result_file.read_text())
    else:
        result = {'status': 'incomplete: inspect failed setup/configure/build step'}
    commands = directory / 'commands.jsonl'
    if commands.exists():
        failed = [command['label'] for line in commands.read_text().splitlines()
                  if (command := json.loads(line))['exit_code']]
        result['failed_commands'] = failed
        result['overall_status'] = 'failed' if failed else result['status']
    write_json(directory / 'summary.json', result)
    text = f'### {args.label}\n\n```json\n{json.dumps(result, indent=2, ensure_ascii=False)}\n```\n'
    print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a', encoding='utf-8') as stream:
            stream.write(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='phase', required=True)
    prep = sub.add_parser('prepare')
    prep.add_argument('--source', type=Path, required=True)
    prep.add_argument('--output', type=Path, required=True)
    prep.add_argument('--archive-dir', type=Path)
    prep.add_argument('--use-updater', action=argparse.BooleanOptionalAction, default=True)
    checked_in = sub.add_parser('prepare-checked-in')
    checked_in.add_argument('--source', type=Path, required=True)
    checked_in.add_argument('--output', type=Path, required=True)
    sub.add_parser('matrix')
    for name in ['unpack', 'external', 'configure', 'build', 'debug-lief', 'test']:
        phase = sub.add_parser(name)
        phase.add_argument('--work', type=Path, required=True)
        phase.add_argument('--results', type=Path, required=True)
        phase.add_argument('--jobs', type=int, default=2)
        if name == 'unpack':
            phase.add_argument('--inputs', type=Path, required=True)
            phase.add_argument('--variant', choices=[f'{m}-{v}' for m in ('bundled', 'shared') for v in VERSIONS], required=True)
            phase.add_argument('--arch', choices=['x64', 'arm64'], required=True)
        if name == 'test':
            phase.add_argument('--execute-sea', action=argparse.BooleanOptionalAction, default=True)
    report = sub.add_parser('summary')
    report.add_argument('--results', type=Path, required=True)
    report.add_argument('--label', required=True)
    args = parser.parse_args()
    functions = {'prepare': prepare, 'prepare-checked-in': prepare_checked_in,
                 'matrix': lambda _: matrix(), 'unpack': unpack,
                 'external': external, 'configure': configure, 'build': build_node,
                 'debug-lief': debug_lief, 'test': test, 'summary': summary}
    functions[args.phase](args)


if __name__ == '__main__':
    main()
