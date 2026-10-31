'use strict';
const common = require('../common');
const assert = require('assert');

if (!common.hasTemporal) {
  common.skip('Temporal is not enabled');
}

// Exercise time zone data loading with small ICU as well as full ICU.
assert.strictEqual(
  globalThis.Temporal.Instant.from('1969-07-20T20:17:00Z').toString(),
  '1969-07-20T20:17:00Z',
);
