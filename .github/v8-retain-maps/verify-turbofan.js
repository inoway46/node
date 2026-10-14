'use strict';

const assert = require('node:assert/strict');
const { AsyncLocalStorage } = require('node:async_hooks');
const console = require('node:console');
const process = require('node:process');
const { setTimeout: delay } = require('node:timers/promises');
const v8 = require('node:v8');
const vm = require('node:vm');

const expectation = process.argv[2];
assert.ok(['baseline', 'fixed'].includes(expectation));
assert.strictEqual(typeof global.gc, 'function');
const storage = new AsyncLocalStorage();
const refs = [];

async function exercise() {
  const context = vm.createContext({});
  refs.push(new WeakRef(vm.runInContext('this', context)));
  const dispatch = vm.runInContext('(async function dispatch() { await 0; })', context);
  context.dispatch = dispatch;
  await storage.run({}, async () => {
    vm.runInContext('%PrepareFunctionForOptimization(dispatch)', context);
    for (let i = 0; i < 100; i++) await dispatch();
    vm.runInContext('%OptimizeFunctionOnNextCall(dispatch)', context);
    await dispatch();
  });
  delete context.dispatch;
}

async function main() {
  console.log(`Node ${process.version}; V8 ${process.versions.v8}; ${process.platform}/${process.arch}; expectation=${expectation}`);
  const counts = [];
  for (let i = 0; i < 8; i++) {
    await exercise();
    await delay(50);
    for (let n = 0; n < 6; n++) global.gc();
    const alive = refs.filter((ref) => ref.deref()).length;
    counts.push(alive);
    console.log(`finished=${i + 1} alive=${alive} native=${v8.getHeapStatistics().number_of_native_contexts}`);
  }
  if (expectation === 'baseline') {
    assert.ok(counts[7] >= 6, 'The official release must reproduce context accumulation');
  } else {
    assert.ok(counts.every((alive) => alive === 0), 'Released realms must be collected');
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
