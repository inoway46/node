import hashlib
import json
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ['GITHUB_WORKSPACE'])
SOURCE = ROOT / 'source'
HARNESS = ROOT / 'harness'
RESULTS = ROOT / 'results'
REPRO = ROOT / 'repro'
RESULTS.mkdir(exist_ok=True)
ROWS = []
FLAGS = ['--ninja', '--without-intl', '--without-npm',
         '--v8-disable-temporal-support']


def capture(command, cwd=None, timeout=60):
    return subprocess.check_output(command, cwd=cwd, text=True, timeout=timeout)


def save_results():
    (RESULTS / 'results.json').write_text(json.dumps(ROWS, indent=2))


def checked_log(command, path, cwd, timeout):
    print('Running:', ' '.join(map(str, command)), flush=True)
    with path.open('w') as log:
        result = subprocess.run(command, cwd=cwd, stdout=log,
                                stderr=subprocess.STDOUT, timeout=timeout, check=False)
    if result.returncode:
        print(path.read_text()[-12000:], flush=True)
        raise RuntimeError(f'{command[0]} failed: {result.returncode}; log: {path}')


def build(label, revision):
    capture(['git', 'checkout', '--detach', revision], cwd=SOURCE)
    # Discard only this experiment's build output for an independent clean build.
    output = SOURCE / 'out'
    if output.exists():
        shutil.rmtree(output)
    for filename in ('config.gypi', 'config.mk', 'icu_config.gypi'):
        (SOURCE / filename).unlink(missing_ok=True)
    checked_log(['./configure', *FLAGS], RESULTS / f'{label}-configure.log', SOURCE, 600)
    checked_log(['ninja', '-C', 'out/Release', '-j3', 'node'],
                RESULTS / f'{label}-build.log', SOURCE, 10800)
    binary = RESULTS / f'node-{label}'
    shutil.copy2(SOURCE / 'out/Release/node', binary)
    metadata = {
        'source_sha': capture(['git', 'rev-parse', 'HEAD'], cwd=SOURCE).strip(),
        'configure_command': ['./configure', *FLAGS],
        'build_command': ['ninja', '-C', 'out/Release', '-j3', 'node'],
        'sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
        'versions': json.loads(capture([str(binary), '-p', 'JSON.stringify(process.versions)'])),
        'platform_arch': capture([str(binary), '-p', 'process.platform+"/"+process.arch']).strip(),
    }
    if metadata['platform_arch'] != 'darwin/arm64':
        raise RuntimeError(f'Unexpected target: {metadata}')
    fingerprint = capture([str(binary), '--allow-natives-syntax', '-e',
                           'const a=[1.5];a.push(undefined);'
                           'console.log(%HasDoubleElements(a),%HasObjectElements(a));'])
    metadata['array_fingerprint'] = fingerprint.strip()
    (RESULTS / f'{label}-metadata.json').write_text(json.dumps(metadata, indent=2))
    return binary


def measure(label, binary):
    for mode, options in [('default', []), ('no-maglev', ['--no-maglev'])]:
        for seed in (1, 2, 3, 7, 9):
            for repeat in range(1, 4):
                # Separate untraced timing from deoptimization instrumentation.
                for traced in (False, True):
                    name = f'{label}-{mode}-seed{seed}-run{repeat}-{"trace" if traced else "timing"}'
                    command = [str(binary), *options]
                    if traced:
                        command.append('--trace-deopt')
                    command += [str(REPRO / 'repro.mjs'), str(seed)]
                    checked_log(command, RESULTS / f'{name}.log', REPRO, 90)
                    log = (RESULTS / f'{name}.log').read_text()
                    elapsed = re.search(r'took (\d+) ms \(true\)', log)
                    if elapsed is None:
                        raise RuntimeError(f'Missing successful reproduction output: {name}')
                    deopts = [line for line in log.splitlines()
                              if 'bailout' in line and 'JSFunction P.div' in line]
                    row = {
                        'label': label, 'mode': mode, 'seed': seed, 'repeat': repeat,
                        'traced': traced, 'command': command, 'exit_code': 0,
                        'milliseconds': int(elapsed.group(1)),
                        'p_div_deopts': len(deopts) if traced else None,
                        'wrong_map_deopts': sum('reason: wrong map' in line for line in deopts)
                        if traced else None,
                    }
                    ROWS.append(row)
                    save_results()
                    print(json.dumps(row), flush=True)


def summarize():
    lines = ['| Mode | Seed | Before ms | After ms | Before wrong-map | After wrong-map |',
             '| --- | ---: | ---: | ---: | ---: | ---: |']
    repeated_before = []
    repeated_after = []
    for mode in ('default', 'no-maglev'):
        for seed in (1, 2, 3, 7, 9):
            values = []
            for label in ('before', 'after'):
                rows = [row for row in ROWS if row['label'] == label
                        and row['mode'] == mode and row['seed'] == seed]
                timing = statistics.median(row['milliseconds'] for row in rows if not row['traced'])
                wrong = statistics.median(row['wrong_map_deopts'] for row in rows if row['traced'])
                values.append((timing, wrong))
                if seed != 1:
                    (repeated_before if label == 'before' else repeated_after).append(wrong)
            lines.append(f'| {mode} | {seed} | {values[0][0]} | {values[1][0]} '
                         f'| {values[0][1]} | {values[1][1]} |')
    if max(repeated_before) < 100:
        outcome = 'INCONCLUSIVE: the baseline did not reproduce a repeated wrong-map loop.'
    elif max(repeated_after) > 10:
        outcome = 'NOT RESOLVED across the tested seeds/modes: repeated deoptimizations remain.'
    else:
        outcome = 'Repeated wrong-map deoptimizations reproduced before and subsided after in this matrix.'
    lines += ['', outcome, '', 'Medians of three fresh processes per seed/mode. Timing is measured without tracing.',
              'This is focused fork validation, separate from normal Node.js CI and V8 CI.']
    report = '\n'.join(lines) + '\n'
    (RESULTS / 'summary.md').write_text(report)
    with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a') as summary:
        summary.write(report)
    print(report, flush=True)


def main():
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise RuntimeError('This experiment requires macOS arm64')
    before = os.environ['BEFORE_SHA']
    after = os.environ['AFTER_SHA']
    parent = capture(['git', 'rev-parse', f'{after}^'], cwd=SOURCE).strip()
    if parent != before:
        raise RuntimeError('Before must be the direct parent of after')
    files = capture(['git', 'diff', '--name-only', before, after], cwd=SOURCE).splitlines()
    if files != ['tools/v8_gypfiles/features.gypi']:
        raise RuntimeError(f'Unexpected source diff: {files}')
    diff = capture(['git', 'diff', before, after], cwd=SOURCE)
    (RESULTS / 'source.patch').write_text(diff)
    environment = {
        'uname': capture(['uname', '-a']).strip(),
        'macos': capture(['sw_vers']).strip(),
        'cpu': capture(['sysctl', '-n', 'machdep.cpu.brand_string']).strip(),
        'memory_bytes': capture(['sysctl', '-n', 'hw.memsize']).strip(),
        'clang': capture(['clang', '--version']).strip(),
        'python': sys.version,
        'ninja': capture(['ninja', '--version']).strip(),
        'before': before, 'after': after, 'workflow_sha': os.environ['GITHUB_SHA'],
        'npm': capture(['npm', '--version']).strip(),
        'repro_sha256': hashlib.sha256((REPRO / 'repro.mjs').read_bytes()).hexdigest(),
    }
    (RESULTS / 'environment.json').write_text(json.dumps(environment, indent=2))
    shutil.copy2(REPRO / 'package-lock.json', RESULTS / 'package-lock.json')
    shutil.copy2(REPRO / 'repro.mjs', RESULTS / 'repro.mjs')
    for label, revision in [('before', before), ('after', after)]:
        binary = build(label, revision)
        measure(label, binary)
    summarize()


if __name__ == '__main__':
    main()
