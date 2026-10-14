'use strict';

const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const console = require('node:console');
const path = require('node:path');
const process = require('node:process');

const runtime = path.resolve(process.argv[2]);
const fixture = path.resolve(process.argv[3]);
const expectation = process.argv[4];
assert.ok(['baseline', 'fixed'].includes(expectation));

const result = spawnSync(runtime, [
  ...process.argv.slice(5),
  '--expose-gc', path.join(fixture, 'node_modules/jest/bin/jest.js'), '--runInBand',
], { cwd: fixture, encoding: 'utf8', timeout: 120000, maxBuffer: 10 * 1024 * 1024 });
process.stdout.write(result.stdout || '');
process.stderr.write(result.stderr || '');
assert.ifError(result.error);
assert.strictEqual(result.status, 0, 'Jest must complete successfully');

const output = result.stdout + result.stderr;
assert.match(output, /Test Suites:\s+8 passed, 8 total/);
assert.match(output, /Tests:\s+3007 passed, 3007 total/);
const counts = [...output.matchAll(
  /test files finished: (\d+), still in memory: (\d+)/g,
)].map((match) => ({ finished: Number(match[1]), alive: Number(match[2]) }));
assert.strictEqual(counts.length, 8, 'Expect a retention count for each test file');
assert.deepStrictEqual(counts.map((count) => count.finished), [1, 2, 3, 4, 5, 6, 7, 8]);
console.log(`Jest retention (${expectation}): ${counts.map((count) => count.alive).join(',')}`);
if (expectation === 'baseline') {
  assert.ok(counts[7].alive >= 6, 'The official release must reproduce context accumulation');
} else {
  // The default map age can temporarily retain the previous realm.
  assert.ok(counts.every((count) => count.alive <= 2), 'Contexts must stop accumulating');
}
