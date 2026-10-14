import Big from 'big.js'

// Deterministic PRNG (mulberry32)
let seed = Number(process.argv[2] ?? 1) >>> 0
const random = () => {
  seed = (seed + 0x6d2b79f5) >>> 0
  let t = seed
  t = Math.imul(t ^ (t >>> 15), t | 1)
  t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296
}

let sink = 0
const start = performance.now()
for (let i = 0; i < 300000; i++) {
  const a = Big((random() * 30).toFixed(2))
  const b = Big((random() * 5 + 0.5).toFixed(i % 3))
  sink += Number(a.times(b).div(i % 2 ? Big(1.255) : b.plus(1)).round(2))
}
console.log(`${process.version} took ${Math.round(performance.now() - start)} ms (${sink > 0})`)
