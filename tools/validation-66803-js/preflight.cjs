'use strict';

// Execute this file using the saved ELF directly, without a QEMU wrapper.
const assert = require('node:assert/strict');
const { spawnSync, fork } = require('node:child_process');
const { Worker } = require('node:worker_threads');

assert.equal(process.arch, 'riscv64');
assert.equal(process.execPath, process.env.EXPECTED_NODE);

if (process.argv[2] === 'child') {
  process.send({ arch: process.arch, execPath: process.execPath });
} else {
  async function main() {
    console.log(JSON.stringify({ arch: process.arch, execPath: process.execPath,
      versions: process.versions, config: process.config }, null, 2));
    const child = spawnSync(process.execPath, ['-p',
      'JSON.stringify({ arch: process.arch, execPath: process.execPath })'],
    { encoding: 'utf8', timeout: 60000 });
    assert.ifError(child.error);
    assert.equal(child.status, 0, child.stderr);
    assert.deepEqual(JSON.parse(child.stdout),
                     { arch: 'riscv64', execPath: process.execPath });
    await new Promise((resolve, reject) => {
      const child = fork(__filename, ['child'], { execPath: process.execPath });
      let messages = 0;
      child.on('error', reject);
      child.on('message', (message) => {
        assert.deepEqual(message, { arch: 'riscv64', execPath: process.execPath });
        messages++;
      });
      child.on('exit', (code, signal) => {
        try {
          assert.equal(code, 0);
          assert.equal(signal, null);
          assert.equal(messages, 1);
          resolve();
        } catch (error) { reject(error); }
      });
    });
    await new Promise((resolve, reject) => {
      const worker = new Worker(`
        const { parentPort } = require('node:worker_threads');
        parentPort.postMessage({ arch: process.arch, execPath: process.execPath });
      `, { eval: true });
      let messages = 0;
      worker.on('error', reject);
      worker.on('message', (message) => {
        assert.deepEqual(message, { arch: 'riscv64', execPath: process.execPath });
        messages++;
      });
      worker.on('exit', (code) => {
        try {
          assert.equal(code, 0);
          assert.equal(messages, 1);
          resolve();
        } catch (error) { reject(error); }
      });
    });
    console.log('direct ELF / process.execPath / spawn / fork / worker: PASS');
  }
  main().catch((error) => { console.error(error); process.exitCode = 1; });
}
