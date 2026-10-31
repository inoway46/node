#!/usr/bin/env python3
"""Compare the #66184 fix against a fixed Node.js main revision."""

import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys


BASE = 'd44625a4b80c672215b469906ce583ce7eeeebaf'
ROOT = Path.cwd()
RESULTS = Path(os.environ['RUNNER_TEMP']) / 'icu-results'
RESULTS.mkdir(exist_ok=True)
PHASE, ICU = sys.argv[1:]
ENV = dict(os.environ, TZ='UTC', LC_ALL='C')
for name in ('NODE_OPTIONS', 'NODE_ICU_DATA', 'ICU_DATA'):
    ENV.pop(name, None)
REPRO = (
    'require("node:assert/strict").equal('
    'Temporal.Instant.from("1969-07-20T20:17:00Z").toString(),'
    '"1969-07-20T20:17:00Z")'
)


def run(label, args, expected=0):
    print(f'{label}: {shlex.join(args)}', flush=True)
    with (RESULTS / f'{label}.log').open('w') as output:
        output.write(f'$ {shlex.join(args)}\n')
        output.flush()
        result = subprocess.run(args, env=ENV, stdout=output,
                                stderr=subprocess.STDOUT, check=False)
        output.write(f'\nexit={result.returncode}\n')
    if result.returncode != expected:
        raise RuntimeError(f'{label}: exit {result.returncode}, expected {expected}')
    return (RESULTS / f'{label}.log').read_text()


def main():
    if PHASE not in ('before', 'after') or ICU not in (
            'small-icu', 'full-icu', 'system-icu'):
        raise ValueError('Invalid matrix configuration')
    candidate = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    patch = subprocess.check_output([
        'git', 'diff', BASE, candidate, '--', 'common.gypi',
        'deps/v8/src/objects/js-temporal-zoneinfo64.cc',
    ])
    regression = (ROOT / 'test/parallel/test-temporal-small-icu.js').read_bytes()
    (RESULTS / 'candidate.patch').write_bytes(patch)
    (RESULTS / 'metadata.json').write_text(json.dumps({
        'base_sha': BASE, 'candidate_sha': candidate, 'phase': PHASE,
        'icu': ICU, 'patch_sha256': hashlib.sha256(patch).hexdigest(),
        'regression_sha256': hashlib.sha256(regression).hexdigest(),
        'configure': ['./configure', f'--with-intl={ICU}',
                      '--v8-enable-temporal-support'],
        'CC': ENV.get('CC'), 'CXX': ENV.get('CXX'),
        'TZ': ENV['TZ'], 'LC_ALL': ENV['LC_ALL'],
    }, indent=2) + '\n')
    run('checkout-base', ['git', 'checkout', '--detach', BASE])
    if PHASE == 'after':
        run('apply-fix', ['git', 'apply', str(RESULTS / 'candidate.patch')])
    (ROOT / 'test/parallel/test-temporal-small-icu.js').write_bytes(regression)
    run('source-diff', ['git', 'diff', '--binary'])
    run('source-status', ['git', 'status', '--short'])
    for tool in ('rustc', 'cargo', 'clang-19', 'python3'):
        run(f'version-{tool}', [tool, '--version'])
    run('configure', ['./configure', f'--with-intl={ICU}',
                      '--v8-enable-temporal-support'])
    for name in ('config.gypi', 'config.status'):
        (RESULTS / name).write_bytes((ROOT / name).read_bytes())
    run('build', ['make', '-j4', 'V=1'])
    node = './out/Release/node'
    run('binary-sha256', ['sha256sum', node])
    run('linked-libraries', ['ldd', node])
    if ICU == 'system-icu':
        run('system-icu-version', ['pkg-config', '--modversion', 'icu-i18n'])
        if 'libicu' not in (RESULTS / 'linked-libraries.log').read_text():
            raise RuntimeError('System ICU is not dynamically linked')
    preflight = '''
const assert = require('node:assert/strict');
const v = process.config.variables;
console.log(JSON.stringify({version: process.version, versions: process.versions,
                           config: v, Temporal: typeof Temporal}, null, 2));
assert.ok([true, 'true', 1].includes(v.v8_enable_temporal_support));
assert.equal(typeof Temporal, 'object');
assert.equal(typeof Intl, 'object');
assert.equal([true, 'true', 1].includes(v.icu_small), process.argv[1] === 'small-icu');
'''
    run('preflight', [node, '-e', preflight, ICU])
    expected = 1 if PHASE == 'before' and ICU == 'small-icu' else 0
    for label, args in (
            ('reproduction', [node, '-e', REPRO]),
            ('regression', [node, 'test/parallel/test-temporal-small-icu.js'])):
        output = run(label, args, expected)
        if 'Skipped:' in output:
            raise RuntimeError(f'{label}: unexpected skip')
        if expected and ('Error: Temporal error: Internal error: '
                         'Failed to load timezone info.') not in output:
            raise RuntimeError(f'{label}: unexpected failure signature')
    run('related-tests', [
        'python3', 'tools/test.py', '--mode=release', '-j2',
        'parallel/test-temporal', 'parallel/test-temporal-with-zoneinfo',
        'parallel/test-intl', 'parallel/test-intl-v8BreakIterator',
        'parallel/test-icu-transcode', 'parallel/test-icu-stringwidth',
        'parallel/test-icu-data-dir',
    ])
    (RESULTS / 'result.json').write_text(json.dumps({
        'phase': PHASE, 'icu': ICU, 'status': 'passed',
        'reproduction': 'expected failure' if expected else 'success',
        'regression': 'expected failure' if expected else 'success',
    }, indent=2) + '\n')
    print('Validation passed; see artifacts for individual test skips.', flush=True)


if __name__ == '__main__':
    main()
