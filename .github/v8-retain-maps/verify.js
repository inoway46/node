'use strict';

const assert = require('node:assert/strict');
const { AsyncLocalStorage } = require('node:async_hooks');
const console = require('node:console');
const process = require('node:process');
const { setTimeout: delay } = require('node:timers/promises');
const vm = require('node:vm');
const v8 = require('node:v8');

const mode = process.argv[2];
const expectation = process.argv[3];
assert.ok(['als', 'minimal'].includes(mode));
assert.ok(['baseline', 'fixed'].includes(expectation));
assert.strictEqual(typeof global.gc, 'function');

const storage = new AsyncLocalStorage();
const refs = [];

async function exercise() {
  const context = vm.createContext({});
  refs.push(new WeakRef(vm.runInContext('this', context)));
  if (mode === 'als') {
    const dispatch = vm.runInContext(
      '(async function dispatch() { await 0; })', context);
    await storage.run({}, async () => {
      for (let i = 0; i < 3000; i++) await dispatch();
    });
  } else {
    await vm.runInContext(`
      async function run() {
        for (let i = 0; i < 3000; i++) await 0;
      }
      run();
    `, context);
  }
}

async function main() {
  console.log(`Node ${process.version}; V8 ${process.versions.v8}; ${process.platform}/${process.arch}; mode=${mode}; expectation=${expectation}`);
  for (let i = 0; i < 8; i++) {
    await exercise();
    await delay(50);
    for (let n = 0; n < 6; n++) global.gc();
    const alive = refs.filter((ref) => ref.deref()).length;
    const native = v8.getHeapStatistics().number_of_native_contexts;
    console.log(`finished=${i + 1} alive=${alive} native=${native}`);
  }
  await delay(50);
  for (let n = 0; n < 6; n++) global.gc();
  const alive = refs.filter((ref) => ref.deref()).length;
  const native = v8.getHeapStatistics().number_of_native_contexts;
  console.log(`final alive=${alive} native=${native}`);
  if (expectation === 'baseline') {
    assert.ok(alive >= 6, `baseline did not reproduce retention: ${alive}`);
  } else {
    assert.ok(alive <= 2, `patched runtime retained too many contexts: ${alive}`);
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
