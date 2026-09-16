import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { appendFileSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const directory = resolve(process.argv[2]);
const fixture = fileURLToPath(new URL('./repro.mjs', import.meta.url));
const trials = Number(process.env.TRIALS || 10);
const controlTrials = Number(process.env.CONTROL_TRIALS || 3);
assert(Number.isInteger(trials) && trials > 0);
assert(Number.isInteger(controlTrials) && controlTrials > 0);
mkdirSync(directory, { recursive: true });

const results = [];
for (const [mode, count, extraFlags] of [
  ['default', trials, []],
  ['no-concurrent-recompilation', controlTrials, ['--no-concurrent-recompilation']],
]) {
  for (let iteration = 1; iteration <= count; iteration++) {
    const args = ['--max-old-space-size=128', ...extraFlags, fixture];
    const start = performance.now();
    const child = spawnSync(process.execPath, args, {
      encoding: 'utf8',
      timeout: 120_000,
      killSignal: 'SIGKILL',
      maxBuffer: 16 * 1024 * 1024,
      env: { ...process.env, NODE_OPTIONS: '' },
    });
    const stdout = child.stdout || '';
    const stderr = child.stderr || '';
    const completed = child.status === 0 && stdout.trim() === 'Completed';
    const oom = !completed && /FATAL ERROR:.*(?:heap|Allocation failed)/.test(stderr);
    const outcome = completed ? 'completed' : oom ? 'oom' : 'other-failure';
    const result = {
      mode, iteration, outcome,
      command: [process.execPath, ...args],
      status: child.status,
      signal: child.signal,
      error: child.error?.message || null,
      durationMs: Math.round(performance.now() - start),
    };
    results.push(result);
    const prefix = resolve(directory, `${mode}-${iteration}`);
    writeFileSync(`${prefix}.stdout.log`, stdout);
    writeFileSync(`${prefix}.stderr.log`, stderr);
    writeFileSync(`${prefix}.json`, `${JSON.stringify(result, null, 2)}\n`);
    console.log(JSON.stringify(result));
  }
}

const counts = {};
for (const mode of ['default', 'no-concurrent-recompilation']) {
  counts[mode] = { 'completed': 0, 'oom': 0, 'other-failure': 0 };
  for (const result of results.filter((result) => result.mode === mode)) {
    counts[mode][result.outcome]++;
  }
}
const summary = {
  variant: process.env.VARIANT || 'local-harness-check',
  version: process.version,
  versions: process.versions,
  platform: process.platform,
  arch: process.arch,
  binarySha256: createHash('sha256').update(readFileSync(process.execPath)).digest('hex'),
  fixtureSha256: createHash('sha256').update(readFileSync(fixture)).digest('hex'),
  counts,
  results,
};
writeFileSync(resolve(directory, 'results.json'), `${JSON.stringify(summary, null, 2)}\n`);
console.log(JSON.stringify({ variant: summary.variant, counts }, null, 2));
if (process.env.GITHUB_STEP_SUMMARY) {
  const lines = [
    `### Issue 66053: ${summary.variant}`,
    '',
    `Node ${process.version}, ${process.platform} ${process.arch}; 128 MiB old-space limit.`,
    '',
    '| Mode | Completed | OOM | Other failure |',
    '| --- | ---: | ---: | ---: |',
    ...Object.entries(counts).map(([mode, count]) =>
      `| ${mode} | ${count.completed} | ${count.oom} | ${count['other-failure']} |`),
    '',
    'A failed baseline run with OOM records is a reproduced bug, not a build failure.',
    'A passing fixed run supports the combined backport for this workload only.',
    '',
  ];
  appendFileSync(process.env.GITHUB_STEP_SUMMARY, lines.join('\n'));
}
process.exitCode = results.every((result) => result.outcome === 'completed') ? 0 : 1;
