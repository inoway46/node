'use strict';
const common = require('../common.js');

const scenarios = [
  'ascii-missing-large',
  'dense-high-byte-missing-large',
  'text-missing-large',
  'one-unit-beginning-large',
  'one-unit-end-large',
  'long-needle-end-large',
  'repeated-prefix-missing-large',
  'small-missing',
];

const bench = common.createBenchmark(main, {
  scenario: scenarios,
  method: ['indexOf', 'lastIndexOf'],
  address: ['aligned', 'unaligned'],
  n: [100],
});

function createInput(scenario) {
  const largeLength = 1024 * 1024;
  let haystack;
  let needle;
  let expected;

  switch (scenario) {
    case 'ascii-missing-large':
      haystack = Buffer.from('A'.repeat(largeLength / 2), 'utf16le');
      needle = '\u0100';
      expected = -1;
      break;
    case 'dense-high-byte-missing-large':
      haystack = Buffer.from('\u0141'.repeat(largeLength / 2), 'utf16le');
      needle = '\u0100';
      expected = -1;
      break;
    case 'text-missing-large': {
      const text = 'The quick brown fox jumps over the lazy dog. ';
      haystack = Buffer.from(
        text.repeat(Math.ceil(largeLength / text.length / 2)),
        'utf16le',
      ).subarray(0, largeLength);
      needle = 'not in this text';
      expected = -1;
      break;
    }
    case 'one-unit-beginning-large':
      haystack = Buffer.from(`Z${'A'.repeat(largeLength / 2 - 1)}`, 'utf16le');
      needle = 'Z';
      expected = 0;
      break;
    case 'one-unit-end-large':
      haystack = Buffer.from(`${'A'.repeat(largeLength / 2 - 1)}Z`, 'utf16le');
      needle = 'Z';
      expected = largeLength - 2;
      break;
    case 'long-needle-end-large': {
      needle = 'NodeBufferSearch';
      const prefixLength = largeLength / 2 - needle.length;
      haystack = Buffer.from(`${'A'.repeat(prefixLength)}${needle}`, 'utf16le');
      expected = largeLength - needle.length * 2;
      break;
    }
    case 'repeated-prefix-missing-large':
      haystack = Buffer.from('A'.repeat(largeLength / 2), 'utf16le');
      needle = 'AAAAAAAB';
      expected = -1;
      break;
    case 'small-missing':
      haystack = Buffer.from('A'.repeat(64), 'utf16le');
      needle = '\u0100';
      expected = -1;
      break;
    default:
      throw new Error(`Unknown scenario: ${scenario}`);
  }

  return { haystack, needle, expected };
}

function main({ n, scenario, method, address }) {
  const input = createInput(scenario);
  let { haystack } = input;
  const { needle, expected } = input;

  if (address === 'unaligned') {
    const backing = Buffer.allocUnsafe(haystack.length + 1);
    haystack.copy(backing, 1);
    haystack = backing.subarray(1);
  }

  const offset = method === 'indexOf' ? 0 : undefined;
  const actual = haystack[method](needle, offset, 'utf16le');
  if (actual !== expected) {
    throw new Error(`Unexpected result: ${actual} !== ${expected}`);
  }

  const iterations = haystack.length <= 128 ? n * 1000 : n;
  bench.start();
  for (let i = 0; i < iterations; i++) {
    haystack[method](needle, offset, 'utf16le');
  }
  bench.end(iterations);
}
