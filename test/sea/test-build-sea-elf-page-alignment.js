'use strict';

const common = require('../common');
if (process.platform !== 'linux')
  common.skip('ELF-specific');

const { buildSEA, skipIfBuildSEAIsNotSupported } = require('../common/sea');
skipIfBuildSEAIsNotSupported();

const assert = require('assert');
const { readFileSync } = require('fs');
const fixtures = require('../common/fixtures');
const tmpdir = require('../common/tmpdir');

function loadSegments(file) {
  const elf = readFileSync(file);
  assert.strictEqual(elf[4], 2);  // ELFCLASS64
  if (elf[5] !== 1) common.skip('Little-endian ELF-specific');
  const phoff = Number(elf.readBigUInt64LE(0x20));
  const phentsize = elf.readUInt16LE(0x36);
  const phnum = elf.readUInt16LE(0x38);
  const loads = [];
  for (let i = 0; i < phnum; i++) {
    const at = phoff + i * phentsize;
    if (elf.readUInt32LE(at) !== 1) continue;  // PT_LOAD
    const memsz = elf.readBigUInt64LE(at + 0x28);
    if (memsz === 0n) continue;
    loads.push({
      offset: elf.readBigUInt64LE(at + 0x08),
      vaddr: elf.readBigUInt64LE(at + 0x10),
      memsz,
      alignment: elf.readBigUInt64LE(at + 0x30),
    });
  }
  assert(loads.length > 0);
  loads.sort((a, b) => (a.vaddr < b.vaddr ? -1 : 1));
  return loads;
}

function pageCompatible(loads, pageSize) {
  return loads.every(({ offset, vaddr }, i) => {
    if (offset % pageSize !== vaddr % pageSize) return false;
    if (i === 0) return true;
    const previous = loads[i - 1];
    return vaddr / pageSize >
      (previous.vaddr + previous.memsz - 1n) / pageSize;
  });
}

const input = loadSegments(process.execPath);
// A binary linked for large pages must retain that compatibility even when
// --build-sea runs on a 4 KiB host. Do not impose it on smaller-page inputs.
const pageSizes = [4096n, 16384n, 65536n].filter((pageSize) =>
  input.every(({ alignment }) => alignment >= pageSize) &&
  pageCompatible(input, pageSize));
if (pageSizes.length === 0)
  common.skip('Input ELF has no disjoint page-compatible LOAD layout');

tmpdir.refresh();
const output = loadSegments(buildSEA(fixtures.path('sea', 'basic')));
for (const pageSize of pageSizes) {
  assert(pageCompatible(output, pageSize),
         `SEA must preserve the input ELF's ${pageSize}-byte page compatibility`);
}
