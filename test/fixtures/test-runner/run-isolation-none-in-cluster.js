'use strict';

const cluster = require('node:cluster');
const { join } = require('node:path');
const { run } = require('node:test');

if (cluster.isPrimary) {
  const worker = cluster.fork();
  worker.on('exit', (code, signal) => {
    if (signal !== null) {
      process.stderr.write(`worker exited with signal ${signal}\n`);
      process.exit(1);
    }

    process.exit(code ?? 0);
  });
} else {
  // Repro based on: https://github.com/nodejs/node/issues/60020
  // We pin `files` for deterministic test discovery in CI.
  const stream = run({
    isolation: 'none',
    files: [
      join(__dirname, 'default-behavior', 'test', 'random.cjs'),
    ],
  });

  stream.on('error', (err) => {
    process.stderr.write(`worker error: ${err}\n`);
    process.exit(1);
  });

  stream.on('data', (data) => {
    process.stdout.write(`on data ${data.type}\n`);
  });

  stream.on('end', () => {
    process.stdout.write('on end\n');
    process.exit(0);
  });

  setTimeout(() => {
    process.stderr.write('worker timed out waiting for end\n');
    process.exit(1);
  }, 3000).unref();
}
