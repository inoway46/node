// Reproduction from https://github.com/nodejs/node/issues/66053.
import { runInNewContext } from 'node:vm';
import { setImmediate } from 'node:timers/promises';

const source = `
  globalThis.payload = new Array(1_000_000).fill(0);
  ${Array.from({ length: 30 }, (_, index) => `
    function work${index}(values) {
      let result = 0;
      for (let i = 0; i < values.length; ++i) {
        result += Math.sqrt(values[i] * values[i] + ${index});
      }
      return result;
    }
  `).join('\n')}
  const values = [1, 2, 3, 4, 5];
  for (let i = 0; i < 1000; ++i) {
    ${Array.from({ length: 30 }, (_, index) => `work${index}(values);`).join('\n')}
  }
`;

for (let i = 0; i < 100; ++i) {
  runInNewContext(source + `\n// ${i}`);
  await setImmediate();
}
console.log('Completed');
