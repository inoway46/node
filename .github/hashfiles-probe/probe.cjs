// Fork-only experiment; not for upstream.
const fs = require('node:fs');
const { HASH, VARIANT, GITHUB_STATE, STATE_initial } = process.env;
if (!STATE_initial) {
  fs.appendFileSync(GITHUB_STATE, `initial=${HASH}\n`);
  console.log(`MAIN_HASH variant=${VARIANT} hash=${HASH}`);
} else {
  const changed = HASH !== STATE_initial;
  console.log(`POST_HASH variant=${VARIANT} changed=${changed} hash=${HASH}`);
  if (changed !== (VARIANT === 'before')) process.exitCode = 1;
}
