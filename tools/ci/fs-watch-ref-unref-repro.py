#!/usr/bin/env python3
"""Fork-only experiment; do not include in the upstream PR.

Uses private copies so metadata injection cannot affect concurrent iterations.
Injection demonstrates sensitivity to metadata changes, not the CI event source.
"""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--node', required=True)
parser.add_argument('--variant', choices=['before', 'after'], required=True)
parser.add_argument('--mode', choices=['plain', 'load', 'metadata'], required=True)
parser.add_argument('--repeat', type=int, default=1000)
parser.add_argument('--jobs', type=int)
parser.add_argument('--output', default='watch-repro-results')
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
base = '50ba1ec6c2b33bf18f21958af500d9e0e8144c7f'
target = 'test/parallel/test-fs-watch-ref-unref.js'
before = subprocess.check_output(['git', 'show', f'{base}:{target}'], cwd=root, text=True)
after = (root / target).read_text()
assert after == before.replace('fs.watch(__filename, common.mustNotCall())', 'fs.watch(__filename)')
assert before != after
source = before if args.variant == 'before' else after
source = source.replace("require('../common')", f'require({json.dumps(str(root / "test/common"))})')
if args.mode == 'metadata':
    injection = """
// The first poll registers the kqueue watcher before this check-phase callback.
watcher.prependListener('change', (event) => {
  if (event === 'change') process.stderr.write('REPRO_METADATA_CHANGE\\n');
});
setImmediate(() => {
  const stat = fs.statSync(__filename);
  fs.utimesSync(__filename, stat.atime, new Date(stat.mtimeMs + 2000));
});
"""
    source = source.replace('watcher.unref();', injection + '\nwatcher.unref();', 1)
cores = os.cpu_count() or 2
jobs = args.jobs or cores * (4 if args.mode == 'load' else 1)
assert args.repeat > 0 and jobs > 0
output = Path(args.output).resolve()
output.mkdir(parents=True, exist_ok=True)
node = str(Path(args.node).resolve())
load = []


def run_one(index):
    with tempfile.TemporaryDirectory(prefix='watch-ref-unref-') as directory:
        test = Path(directory) / Path(target).name
        test.write_text(source)
        try:
            result = subprocess.run([node, str(test)], cwd=root, capture_output=True,
                                    text=True, timeout=30)
            stderr = result.stderr
            return {'iteration': index, 'exit': result.returncode,
                    'observed': 'REPRO_METADATA_CHANGE' in stderr,
                    'expected_failure': result.returncode != 0 and
                    'function should not have been called' in stderr and
                    "called with arguments: 'change', 'test-fs-watch-ref-unref.js'" in stderr,
                    'stdout': result.stdout, 'stderr': stderr}
        except subprocess.TimeoutExpired:
            return {'iteration': index, 'exit': 'timeout', 'observed': False,
                    'expected_failure': False}


results = []
try:
    if args.mode == 'load':
        for _ in range(cores * 2):
            load.append(subprocess.Popen(['yes'], stdout=subprocess.DEVNULL))
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        with (output / 'results.jsonl').open('w') as log:
            for result in pool.map(run_one, range(args.repeat)):
                log.write(json.dumps(result) + '\n')
                log.flush()
                results.append(result)
finally:
    for process in load:
        process.terminate()
    for process in load:
        process.wait()
passed = sum(r['exit'] == 0 for r in results)
failed = len(results) - passed
observed = sum(r['observed'] for r in results)
expected = sum(r['expected_failure'] for r in results)
if args.mode == 'metadata':
    valid = observed == args.repeat and (
        expected == args.repeat if args.variant == 'before' else passed == args.repeat)
else:
    # Before may naturally reproduce the known failure; unrelated errors still fail.
    valid = passed == args.repeat or (args.variant == 'before' and failed == expected)
summary = {'variant': args.variant, 'mode': args.mode, 'repeat': args.repeat,
           'jobs': jobs, 'pass': passed, 'fail': failed, 'observed': observed,
           'expected_failures': expected, 'valid': valid, 'base': base,
           'runtime': subprocess.check_output([node, '--version'], text=True).strip()}
(output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps(summary), flush=True)
if os.environ.get('GITHUB_STEP_SUMMARY'):
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
        stream.write('| variant | mode | pass | fail | observed changes | valid |\n'
                     '|---|---|---|---|---|---|\n'
                     f'| {args.variant} | {args.mode} | {passed} | {failed} | {observed} | {valid} |\n')
raise SystemExit(0 if valid else 1)
