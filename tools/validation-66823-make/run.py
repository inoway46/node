"""Compare Make's bundled Temporal cross-build actions before and after #66823."""

import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile

BASE = '697ecce05e7d72cf9278cae15278f51016d6e3b2'
HEAD = '5ff420e05b794b8aac9d0cb07f1867a8f5463487'
HOST = 'x86_64-unknown-linux-gnu'
ARCHES = {
    'arm64': ('aarch64-unknown-linux-gnu', 'aarch64-linux-gnu', 'aarch64', 'AArch64'),
    'riscv64': ('riscv64gc-unknown-linux-gnu', 'riscv64-linux-gnu', 'riscv64', 'RISC-V'),
}
PROBE = '''#include "PlainDate.h"
int main(void) {
  temporal_rs_PlainDate_try_new_result date =
      temporal_rs_PlainDate_try_new(2024, 2, 29, AnyCalendarKind_Iso);
  if (!date.is_ok) return 1;
  int result = temporal_rs_PlainDate_is_valid(date.ok) &&
      temporal_rs_PlainDate_year(date.ok) == 2024 &&
      temporal_rs_PlainDate_month(date.ok) == 2 ? 0 : 2;
  temporal_rs_PlainDate_destroy(date.ok);
  return result;
}
'''
CAPTURE = '''import json, os, runpy, sys
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), 'tools/gyp/pylib'))
import gyp
original = gyp.Load
def capture(*args, **kwargs):
    result = original(*args, **kwargs)
    with open(os.environ['VALIDATION_GRAPH'], 'w') as f:
        json.dump(result[2], f, indent=2)
    return result
gyp.Load = capture
sys.argv[0] = 'configure.py'
runpy.run_path('configure.py', run_name='__main__')
'''


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class Validation:
    def __init__(self, args):
        self.arch = args.arch
        self.triple, self.prefix, self.qemu_arch, self.machine = ARCHES[args.arch]
        self.output = args.output.resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.work = args.work.resolve()
        self.work.mkdir(parents=True, exist_ok=True)
        self.sources = args.sources.resolve()
        self.env = dict(os.environ)
        for key in ('RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'CARGO_BUILD_TARGET',
                    'GYP_DEFINES', 'CARGO_TARGET_DIR', 'RUSTC_WRAPPER',
                    'RUSTC_WORKSPACE_WRAPPER'):
            self.env.pop(key, None)
        self.env.update({
            'LC_ALL': 'C', 'CC': self.prefix + '-gcc', 'CXX': self.prefix + '-g++',
            'AR': self.prefix + '-ar', 'CC_host': 'gcc', 'CXX_host': 'g++',
            'AR_host': 'ar', 'CARGO_BUILD_TARGET': self.triple,
            'CARGO_BUILD_JOBS': '2', 'RUSTUP_TOOLCHAIN': '1.88.0',
            'CARGO_TARGET_' + self.triple.upper().replace('-', '_') + '_LINKER':
                self.prefix + '-gcc',
        })
        self.env.update({key + '_target': self.env[key] for key in ('CC', 'CXX', 'AR')})
        self.results = {'base': BASE, 'head': HEAD, 'arch': args.arch,
                        'profile': 'Release', 'generator': 'Make',
                        'pr66804_included': False, 'commands': {}, 'cases': {}}
        self.probe = self.output / 'ffi.c'
        self.probe.write_text(PROBE)
        self.capture = self.output / 'capture.py'
        self.capture.write_text(CAPTURE)

    def save(self):
        (self.output / 'results.json').write_text(json.dumps(self.results, indent=2) + '\n')

    def run(self, name, command, cwd, expected_failure=None):
        path = self.output / (name + '.log')
        with path.open('w') as log:
            log.write('$ ' + shlex.join(map(str, command)) + '\n')
            log.flush()
            proc = subprocess.run(command, cwd=cwd, env=self.env, stdout=log,
                                  stderr=subprocess.STDOUT, check=False)
        text = path.read_text(errors='replace')
        self.results['commands'][name] = {'command': list(map(str, command)),
                                          'exit': proc.returncode}
        self.save()
        print(f'{name}: exit {proc.returncode}', flush=True)
        if expected_failure:
            require(proc.returncode != 0 and re.search(expected_failure, text),
                    f'{name}: expected diagnostic not found; see {path}')
        elif proc.returncode:
            print(text[-6000:], flush=True)
            raise RuntimeError(f'{name}: failed; see {path}')
        return text

    def inspect_archive(self, label, path, machine):
        text = self.run(label + '-headers', ['readelf', '-h', path], self.work)
        machines = collections.Counter(re.findall(r'Machine:\s+([^\n]+)', text))
        require(set(machines) == {machine}, f'{label}: unexpected ELF members {machines}')
        return {'path': str(path), 'machines': dict(machines),
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    def link(self, label, source, archive, host, expected_failure=None):
        compiler = 'gcc' if host else self.prefix + '-gcc'
        exe = self.work / label
        flags = ['-march=rv64gc', '-mabi=lp64d'] if not host and self.arch == 'riscv64' else []
        self.run(label, [compiler, *flags, '-std=c11', '-I',
                        source / 'deps/crates/vendor/temporal_capi-v0_2/bindings/c',
                        self.probe, archive, '-ldl', '-lpthread', '-lm', '-lrt',
                        '-lutil', '-o', exe], source, expected_failure)
        if not expected_failure:
            command = [exe] if host else ['qemu-' + self.qemu_arch, '-L',
                                          '/usr/' + self.prefix, exe]
            self.run(label + '-run', command, source)

    def case(self, kind):
        source = self.work / kind
        require(not source.exists(), f'{source} must be a clean directory')
        source.mkdir()
        with tarfile.open(self.sources / (kind + '.tar')) as archive:
            archive.extractall(source, filter='data')
        self.env['VALIDATION_GRAPH'] = str(self.output / (kind + '-graph.json'))
        self.run(kind + '-configure', [sys.executable, self.capture, '--cross-compiling',
                                      '--dest-os=linux', '--dest-cpu=' + self.arch,
                                      '--v8-enable-temporal-support', '--verbose'], source)
        shutil.copy(source / 'config.gypi', self.output / (kind + '-config.gypi'))
        graph = json.loads(Path(self.env['VALIDATION_GRAPH']).read_text())
        rust = {key.rsplit('#', 1)[1]: value for key, value in graph.items()
                if ':node_crates#' in key}
        require(set(rust) == {'host', 'target'}, 'Expected both Rust toolsets')
        outputs = {toolset: value['actions'][0]['outputs'][0].replace(
            '$(obj)', str(source / 'out/Release/obj')) for toolset, value in rust.items()}
        for toolset in rust:
            shutil.copy(source / f'out/deps/crates/node_crates.{toolset}.mk',
                        self.output / f'{kind}-node_crates.{toolset}.mk')
        result = {'declared_outputs': outputs, 'archives': {}}
        self.results['cases'][kind] = result
        make = ['make', '-C', 'out', 'BUILDTYPE=Release', 'V=1', '-j2']
        if kind == 'before':
            require(outputs['host'] == outputs['target'], 'Baseline outputs must collide')
            for value in rust.values():
                require('--target' not in value['actions'][0]['action'],
                        'Baseline unexpectedly selects a toolset-specific target')
            self.run('before-build', make + [outputs['host']], source)
            declared = Path(outputs['host'])
            actual = source / f'out/Release/obj/gen/{self.triple}/release/libnode_crates.a'
            require(not declared.exists(), 'Expected baseline declared archive to be absent')
            require(actual.is_file(), 'Cargo did not produce the expected target archive')
            result['declared_archive_exists'] = False
            result['archives']['target'] = self.inspect_archive('before-target', actual,
                                                                self.machine)
            for host in (True, False):
                self.link('before-declared-' + ('host' if host else 'target'), source,
                          declared, host, r'cannot find .*libnode_crates\.a')
            self.link('before-actual-host', source, actual, True,
                      r'file in wrong format|Relocations in generic ELF|incompatible')
            self.link('before-target-control', source, actual, False)
        else:
            require(outputs['host'] != outputs['target'], 'Fixed outputs must differ')
            producers = collections.Counter(path for value in graph.values()
                                            for action in value.get('actions', [])
                                            for path in action.get('outputs', []))
            for toolset, value in rust.items():
                triple = HOST if toolset == 'host' else self.triple
                action = value['actions'][0]
                require(action['action'][action['action'].index('--target') + 1] == triple,
                        'Incorrect Cargo target')
                require(f'/cargo/{toolset}/{triple}/release/' in outputs[toolset],
                        'Incorrect Cargo output directory')
                require(producers[action['outputs'][0]] == 1, 'Multiple Rust producers')
            for suffix, toolset in [(':mksnapshot#host', 'host'), (':node#target', 'target')]:
                value = next(value for key, value in graph.items() if key.endswith(suffix))
                libraries = [lib for lib in value['libraries'] if 'node_crates' in lib]
                require(len(libraries) == 1 and '/cargo/' + toolset + '/' in libraries[0],
                        'Incorrect Rust archive propagation to ' + suffix)
            self.run('after-build', make + list(outputs.values()), source)
            repeat = self.run('after-repeat', make + list(outputs.values()), source)
            require('cargo rustc' not in repeat, 'Incremental build invoked Cargo again')
            for toolset, filename in outputs.items():
                path = Path(filename)
                require(path.is_file(), f'Declared output missing: {path}')
                host = toolset == 'host'
                machine = 'Advanced Micro Devices X86-64' if host else self.machine
                result['archives'][toolset] = self.inspect_archive('after-' + toolset,
                                                                   path, machine)
                self.link('after-' + toolset, source, path, host)
        self.save()

    def execute(self):
        for label, command in [('uname', ['uname', '-a']), ('rust', ['rustc', '-vV']),
                               ('cargo', ['cargo', '-V']), ('host-cc', ['gcc', '--version']),
                               ('target-cc', [self.prefix + '-gcc', '-v']),
                               ('qemu', ['qemu-' + self.qemu_arch, '--version'])]:
            self.run('version-' + label, command, self.work)
        self.case('before')
        self.case('after')
        self.results['outcome'] = 'PASS: expected baseline failures and fixed archive/FFI success'
        self.save()
        summary = (f'### Make / Release / {self.arch}\n\n'
                   f'- Before: `{BASE}` — expected missing archive and host link failures reproduced.\n'
                   f'- After: `{HEAD}` — separate host/target archives, correct ELF architectures, '
                   'Temporal FFI links and native/QEMU execution passed; incremental build was a no-op.\n'
                   '- #66804 excluded. Full Node.js build and Ninja are outside this validation.\n')
        (self.output / 'summary.md').write_text(summary)
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
                stream.write(summary)
        print(summary, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arch', choices=ARCHES, required=True)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    validation = Validation(parser.parse_args())
    try:
        validation.execute()
    except Exception as error:
        validation.results['error'] = str(error)
        validation.save()
        raise


if __name__ == '__main__':
    main()
