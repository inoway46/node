'use strict';
const fs = require('node:fs');
const [path, size] = process.argv.slice(2);
const page = Number(size);
const b = fs.readFileSync(path);
if (b.subarray(0, 6).toString('hex') !== '7f454c460201' || b.readUInt16LE(18) !== 183) throw Error('Expected AArch64 ELF64LE');
const u64 = o => Number(b.readBigUInt64LE(o));
const loads = [];
const errors = [];
for (let i = 0; i < b.readUInt16LE(56); i++) {
  const o = u64(32) + i * b.readUInt16LE(54);
  if (b.readUInt32LE(o) === 1 && u64(o + 40)) {
    const s = {index:i, offset:u64(o+8), va:u64(o+16), filesz:u64(o+32), memsz:u64(o+40), alignment:u64(o+48)};
    loads.push(s);
    if (s.va % page !== s.offset % page) errors.push(`LOAD ${i}: incongruent`);
  }
}
for (let i = 0; i < loads.length; i++) for (const b of loads.slice(i+1)) {
  const a = loads[i];
  if (Math.max(Math.floor(a.va/page), Math.floor(b.va/page)) < Math.min(Math.ceil((a.va+a.memsz)/page), Math.ceil((b.va+b.memsz)/page))) errors.push(`LOAD ${a.index}/${b.index}: overlapping pages`);
}
console.log(JSON.stringify({path, page, loads, errors}, null, 2));
if (!loads.length || errors.length) process.exitCode = 1;
