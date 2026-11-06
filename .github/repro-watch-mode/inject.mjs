// Fault injection preload (`--import`): simulate a watcher that starts
// reporting late, like an FSEvents stream that is not scheduled yet, by
// dropping the 'change' events of every `fs.watch()` watcher for DROP_MS
// milliseconds after it is created.
import fs from 'node:fs';
import { performance } from 'node:perf_hooks';

const originalWatch = fs.watch;
const DROP_MS = Number(process.env.DROP_MS ?? 500);

fs.watch = function watch(...args) {
  const watcher = originalWatch.apply(this, args);
  const createdAt = performance.now();
  const emit = watcher.emit;
  watcher.emit = function(event, ...rest) {
    if (event === 'change' && performance.now() - createdAt < DROP_MS) {
      return false;
    }
    return emit.call(this, event, ...rest);
  };
  return watcher;
};
