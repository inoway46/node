// Copyright Node.js contributors. All rights reserved.
// SPDX-License-Identifier: MIT

'use strict';
const assert = require('node:assert/strict');
const vm = require('node:vm');
const crypto = require('node:crypto');
const zlib = require('node:zlib');
assert.strictEqual(process.arch, 'riscv64');
assert.strictEqual(process.platform, 'linux');
assert.strictEqual(process.config.variables.v8_enable_temporal_support, 1);
const { Temporal } = globalThis;
assert.ok(Temporal);
assert.strictEqual(Temporal.PlainDate.from('2024-02-29').add({ days: 1 }).toString(), '2024-03-01');
assert.strictEqual(Temporal.Instant.from('2024-02-29T12:34:56Z').toString(), '2024-02-29T12:34:56Z');
assert.throws(() => Temporal.PlainDate.from('2024-02-30'), RangeError);
let jsonCases = 0;
function quote(s) {
  let out = '"';
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c === 34 || c === 92) out += '\\' + s[i];
    else if (c === 8) out += '\\b';
    else if (c === 9) out += '\\t';
    else if (c === 10) out += '\\n';
    else if (c === 12) out += '\\f';
    else if (c === 13) out += '\\r';
    else if (c < 32) out += '\\u' + c.toString(16).padStart(4, '0');
    else if (c >= 0xd800 && c <= 0xdbff && i + 1 < s.length &&
             s.charCodeAt(i + 1) >= 0xdc00 && s.charCodeAt(i + 1) <= 0xdfff)
      out += s[i] + s[++i];
    else if (c >= 0xd800 && c <= 0xdfff)
      out += '\\u' + c.toString(16).padStart(4, '0');
    else out += s[i];
  }
  return out + '"';
}

function check(s) {
  const expected = quote(s);
  assert.strictEqual(JSON.stringify(s), expected);
  assert.strictEqual(JSON.parse(expected), s);
  assert.strictEqual(JSON.stringify([{ value: s, tail: 'tail' }]),
                     '[{"value":' + expected + ',"tail":"tail"}]');
  assert.strictEqual(JSON.parse('{"value":' + expected + '}').value, s);
  jsonCases++;
}
const specials = [0, 1, 8, 9, 10, 12, 13, 31, 34, 92, 127, 128, 255, 256, 0x2028, 0x2029, 0xd800, 0xdc00]
  .map((c) => String.fromCharCode(c)).concat(['\ud83d\ude00', '\ud800X\udc00']);
for (let len = 0; len <= 129; len++) {
  check('a'.repeat(len));
  check('\u0100'.repeat(len));
  for (const pos of new Set([0, Math.floor(len / 2), len])) {
    for (const special of specials) {
      check('a'.repeat(pos) + special + 'b'.repeat(len - pos));
      check('\u0100'.repeat(pos) + special + '\u0101'.repeat(len - pos));
    }
  }
}
for (const bad of ['"unterminated', '"bad\\x"', '"raw\nnewline"', '"\\uXXXX"'])
  assert.throws(() => JSON.parse(bad), SyntaxError);
const dict = { __proto__: null };
for (let i = 0; i < 4096; i++) dict['key-' + i + (i % 2 ? '\u0100' : '\u00ff')] = i;
assert.deepStrictEqual({ ...dict }, JSON.parse(JSON.stringify(dict)));
let lineCases = 0;
for (let pad = 0; pad <= 33; pad++) {
  for (const nl of ['\n', '\r', '\r\n', '\u2028', '\u2029']) {
    const name = 'line-check-' + pad + '-' + lineCases + '.js';
    try {
      vm.runInNewContext(' '.repeat(pad) + nl + "throw new Error('marker')", {}, { filename: name });
      assert.fail('Expected error');
    } catch (e) {
      assert.match(e.stack, new RegExp(name.replaceAll('.', '\\.') + ':2:'));
    }
    assert.strictEqual(vm.runInNewContext(' '.repeat(pad) + nl), undefined);
    lineCases++;
  }
}
assert.strictEqual(vm.runInNewContext(''), undefined);
assert.strictEqual(crypto.createHash('sha256').update('abc').digest('hex'),
                   'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
const buf = Buffer.from('hello \u0100 \ud83d\ude00'.repeat(100));
assert.deepStrictEqual(zlib.gunzipSync(zlib.gzipSync(buf)), buf);
const wasm = new WebAssembly.Instance(new WebAssembly.Module(Uint8Array.from([
  0, 97, 115, 109, 1, 0, 0, 0, 1, 5, 1, 96, 0, 1, 127, 3, 2, 1, 0,
  7, 7, 1, 3, 97, 110, 115, 0, 0, 10, 6, 1, 4, 0, 65, 42, 11])));
assert.strictEqual(wasm.exports.ans(), 42);
setImmediate(() => {
  console.log(JSON.stringify({
    status: 'passed', node: process.version, v8: process.versions.v8,
    arch: process.arch, temporal: process.config.variables.v8_enable_temporal_support,
    jsonCases, lineCases, hashKeys: 4096,
    checks: ['Temporal PlainDate/Instant', 'JSON parse/stringify', 'Latin1/UC16/surrogates',
             'property keys', 'line endings and stack positions', 'crypto', 'zlib',
             'WebAssembly', 'event loop'],
  }));
});
