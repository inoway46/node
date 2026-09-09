'use strict';
require('../common');
const assert = require('assert');

const encodings = ['utf16le', 'utf-16le', 'ucs2', 'ucs-2'];

function normalizeOffset(length, offset, needleLength, forward) {
  if (offset < 0) {
    if (offset + length >= 0) return length + offset;
    return forward ? 0 : -1;
  }
  if (offset + needleLength <= length) return offset;
  return forward ? -1 : length - 1;
}

function bytesEqual(haystack, candidate, needle) {
  for (let i = 0; i < needle.length; i++) {
    if (haystack[candidate + i] !== needle[i]) return false;
  }
  return true;
}

function referenceSearch(haystack, value, start, end, forward) {
  const needle = Buffer.from(value, 'utf16le');
  assert.notStrictEqual(needle.length, 0);

  const searchEnd = Math.min(Math.max(end, 0), haystack.length);
  const haystackLength = haystack.length - haystack.length % 2;
  let offset = normalizeOffset(haystackLength, start, needle.length, forward);
  if (offset < 0) return -1;

  if (!forward && offset >= searchEnd) {
    if (searchEnd === 0) return -1;
    offset = searchEnd - 1;
  } else if (forward && offset >= searchEnd) {
    return -1;
  }

  if (forward) {
    offset += offset % 2;
    if (offset >= searchEnd) return -1;
  } else {
    offset -= offset % 2;
  }

  if (needle.length > searchEnd ||
      (forward && needle.length + offset > searchEnd)) {
    return -1;
  }

  const lastCandidate = searchEnd - needle.length;
  if (forward) {
    for (let candidate = offset; candidate <= lastCandidate; candidate += 2) {
      if (bytesEqual(haystack, candidate, needle)) return candidate;
    }
  } else {
    let candidate = Math.min(offset, lastCandidate);
    candidate -= candidate % 2;
    for (; candidate >= 0; candidate -= 2) {
      if (bytesEqual(haystack, candidate, needle)) return candidate;
    }
  }
  return -1;
}

{
  const value = '\u6881\u6882\u6881';
  for (const encoding of encodings) {
    const buf = Buffer.from(value, encoding);

    assert.strictEqual(buf.indexOf('\u6881', 0, encoding), 0);
    assert.strictEqual(buf.indexOf('\u6881', 1, encoding), 4);
    assert.strictEqual(buf.indexOf('\u6881', 2, encoding), 4);
    assert.strictEqual(buf.indexOf('\u6881', 3, encoding), 4);
    assert.strictEqual(buf.indexOf('\u6881', 4, encoding), 4);
    assert.strictEqual(buf.indexOf('\u6881', 5, encoding), -1);
    assert.strictEqual(buf.indexOf('\u6881', -5, encoding), 4);
    assert.strictEqual(buf.indexOf('\u6881', -7, encoding), 0);
    assert.strictEqual(buf.indexOf('\u6881', 7, encoding), -1);

    assert.strictEqual(buf.lastIndexOf('\u6881', undefined, encoding), 4);
    assert.strictEqual(buf.lastIndexOf('\u6881', 5, encoding), 4);
    assert.strictEqual(buf.lastIndexOf('\u6881', 4, encoding), 4);
    assert.strictEqual(buf.lastIndexOf('\u6881', 3, encoding), 0);
    assert.strictEqual(buf.lastIndexOf('\u6881', 1, encoding), 0);
    assert.strictEqual(buf.lastIndexOf('\u6881', -3, encoding), 0);
    assert.strictEqual(buf.lastIndexOf('\u6881', -7, encoding), -1);

    assert.strictEqual(buf.includes('\u6881', 1, encoding), true);
    assert.strictEqual(buf.includes('\u6881', 5, encoding), false);

    assert.strictEqual(buf.indexOf('\u6881', 1, 5, encoding), -1);
    assert.strictEqual(buf.indexOf('\u6881', 1, 6, encoding), 4);
    assert.strictEqual(buf.indexOf('\u6881', 0, 3, encoding), 0);
    assert.strictEqual(buf.indexOf('\u6881', 0, 1, encoding), -1);
    assert.strictEqual(buf.lastIndexOf('\u6881', 5, 5, encoding), 0);
    assert.strictEqual(buf.lastIndexOf('\u6881', 5, 6, encoding), 4);
  }
}

{
  const buf = Buffer.from([
    0x41, 0x00,
    0x01, 0x00,
    0x00, 0x01,
  ]);

  assert.strictEqual(buf.indexOf('\u0100', 0, 'utf16le'), 4);
  assert.strictEqual(buf.lastIndexOf('\u0100', undefined, 'utf16le'), 4);
  assert.strictEqual(buf.includes('\u0100', 0, 'utf16le'), true);
}

{
  const value = '\u6881\u6882\u6881';
  const prefixed = Buffer.alloc(7);
  prefixed.write(value, 1, 'utf16le');

  assert.strictEqual(prefixed.indexOf(value, 0, 'utf16le'), -1);
  assert.strictEqual(prefixed.indexOf(value, 1, 'utf16le'), -1);

  const payload = prefixed.subarray(1);
  assert.strictEqual(payload.indexOf(value, 0, 'utf16le'), 0);
  assert.strictEqual(payload.includes(value, 0, 'utf16le'), true);
  assert.strictEqual(
    prefixed.indexOf(Buffer.from(value, 'utf16le')),
    1,
  );

  const direct = Buffer.from(value, 'utf16le');
  assert.strictEqual(direct.subarray(1).indexOf('\u6881', 0, 'utf16le'), -1);
}

{
  assert.strictEqual(
    Buffer.from('00aaaa', 'hex').indexOf('\uaaaa', 0, 'utf16le'),
    -1,
  );
  assert.strictEqual(
    Buffer.from('0000aaaa', 'hex').indexOf('\uaaaa', 0, 'utf16le'),
    2,
  );
}

{
  const bytes = Buffer.from('A\ud83d\ude00B\ud83d\ude00', 'utf16le');
  assert.strictEqual(bytes.indexOf('\ud83d\ude00', 0, 'utf16le'), 2);
  assert.strictEqual(bytes.indexOf('\ud83d\ude00', 3, 'utf16le'), 8);
  assert.strictEqual(bytes.lastIndexOf('\ud83d\ude00', 7, 'utf16le'), 2);

  assert.strictEqual(Buffer.from([0x41, 0x00, 0x42])
    .indexOf('\u0042', 0, 'utf16le'), -1);
  assert.strictEqual(Buffer.alloc(0).indexOf('A', 0, 'utf16le'), -1);
  assert.strictEqual(Buffer.from('A', 'utf16le')
    .indexOf('AB', 0, 'utf16le'), -1);
}

{
  const oddLength = Buffer.from([0x41, 0x00, 0x42, 0x00, 0xff]);
  assert.strictEqual(oddLength.indexOf('B', -2, 'utf16le'), 2);
  assert.strictEqual(oddLength.indexOf('B', -3, 'utf16le'), 2);
  assert.strictEqual(oddLength.lastIndexOf('B', -2, 'utf16le'), 2);
  assert.strictEqual(oddLength.lastIndexOf('B', -3, 'utf16le'), -1);

  // Preserve the existing offset normalization for odd-length haystacks.
  assert.strictEqual(oddLength.indexOf('', 5, 5, 'utf16le'), 4);
  assert.strictEqual(oddLength.lastIndexOf('', 5, 5, 'utf16le'), 4);
  assert.strictEqual(Buffer.alloc(0).indexOf('', 0, 'utf16le'), 0);
}

{
  const logical = Buffer.from('\u6881\u6882\u6881', 'utf16le');
  for (const prefixLength of [0, 1]) {
    const backing = Buffer.alloc(prefixLength + logical.length);
    logical.copy(backing, prefixLength);
    const view = backing.subarray(prefixLength);
    assert.strictEqual(view.indexOf('\u6881', 1, 'utf16le'), 4);
    assert.strictEqual(view.lastIndexOf('\u6881', 3, 'utf16le'), 0);
  }
}

{
  const raw = Buffer.from('00aaaa', 'hex');
  const bufferNeedle = Buffer.from('\uaaaa', 'utf16le');
  const uint8ArrayNeedle = new Uint8Array(bufferNeedle);

  assert.strictEqual(raw.indexOf(bufferNeedle), 1);
  assert.strictEqual(raw.indexOf(uint8ArrayNeedle), 1);
  assert.strictEqual(raw.indexOf(bufferNeedle, 0, 'utf16le'), -1);
  assert.strictEqual(raw.indexOf(uint8ArrayNeedle, 0, 'utf16le'), -1);
  assert.strictEqual(raw.indexOf(0xaa, 0, 'utf16le'), 1);
  assert.strictEqual(Buffer.from('abc').indexOf('b', 0, 'utf8'), 1);
}

{
  const uint8Array = Uint8Array.of(0x41, 0x00, 0x01, 0x00, 0x00, 0x01);
  const { indexOf, lastIndexOf, includes } = Buffer.prototype;

  assert.strictEqual(indexOf.call(uint8Array, '\u0100', 0, 'utf16le'), 4);
  assert.strictEqual(
    lastIndexOf.call(uint8Array, '\u0100', undefined, 'utf16le'),
    4,
  );
  assert.strictEqual(includes.call(uint8Array, '\u0100', 0, 'utf16le'), true);
}

{
  const haystacks = [
    Buffer.alloc(0),
    Buffer.from([0x00]),
    Buffer.from([0x00, 0x01]),
    Buffer.from([0x41, 0x00, 0x01, 0x00, 0x00, 0x01]),
    Buffer.from('A\ud83d\ude00B\u0100', 'utf16le'),
  ];
  for (let length = 1; length <= 7; length++) {
    for (let bits = 0; bits < 2 ** length; bits++) {
      const bytes = Buffer.alloc(length);
      for (let i = 0; i < length; i++) bytes[i] = (bits >> i) & 1;
      haystacks.push(bytes);
    }
  }

  const needles = ['\u0000', '\u0001', '\u0100', 'A', 'AB', '\ud83d\ude00'];
  for (const haystack of haystacks) {
    const starts = [
      -haystack.length - 1,
      -3,
      -2,
      -1,
      0,
      1,
      2,
      haystack.length - 1,
      haystack.length,
      haystack.length + 1,
    ];
    const ends = [
      0,
      1,
      2,
      haystack.length - 1,
      haystack.length,
      haystack.length + 1,
    ];

    for (const needle of needles) {
      for (const start of starts) {
        for (const end of ends) {
          const forward = referenceSearch(haystack, needle, start, end, true);
          const reverse = referenceSearch(haystack, needle, start, end, false);
          assert.strictEqual(
            haystack.indexOf(needle, start, end, 'utf16le'),
            forward,
          );
          assert.strictEqual(
            haystack.lastIndexOf(needle, start, end, 'utf16le'),
            reverse,
          );
          assert.strictEqual(
            haystack.includes(needle, start, end, 'utf16le'),
            forward !== -1,
          );
        }
      }
    }
  }
}
