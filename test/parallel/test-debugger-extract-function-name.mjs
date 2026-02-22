import { skipIfInspectorDisabled } from '../common/index.mjs';

skipIfInspectorDisabled();

import * as fixtures from '../common/fixtures.mjs';
import startCLI from '../common/debugger.js';

import assert from 'assert';

const cli = startCLI([fixtures.path('debugger', 'three-lines.js')]);

try {
  await cli.waitFor(/Debugger attached\./);
  await cli.waitForPrompt();
  cli.writeLine('exec a = function func() {}; a;', true);
  await cli.waitFor(/\[Function: func\]/);
  await cli.waitForPrompt();
  assert.match(cli.output, /\[Function: func\]/);

  cli.writeLine('exec a = function func () {}; a;', true);
  await cli.waitFor(/\[Function\]/);
  await cli.waitForPrompt();
  assert.match(cli.output, /\[Function\]/);

  cli.writeLine('exec a = function() {}; a;', true);
  await cli.waitFor(/\[Function: function\]/);
  await cli.waitForPrompt();
  assert.match(cli.output, /\[Function: function\]/);

  cli.writeLine('exec a = () => {}; a;', true);
  await cli.waitFor(/\[Function\]/);
  await cli.waitForPrompt();
  assert.match(cli.output, /\[Function\]/);

  cli.writeLine('exec a = function* func() {}; a;', true);
  await cli.waitFor(/\[GeneratorFunction: func\]/);
  await cli.waitForPrompt();
  assert.match(cli.output, /\[GeneratorFunction: func\]/);

  cli.writeLine('exec a = function *func() {}; a;', true);
  await cli.waitFor(/\[GeneratorFunction: \*func\]/);
  await cli.waitForPrompt();
  assert.match(cli.output, /\[GeneratorFunction: \*func\]/);

  cli.writeLine('exec a = function*func() {}; a;', true);
  await cli.waitFor(/\[GeneratorFunction: function\*func\]/);
  await cli.waitForPrompt();
  assert.match(cli.output, /\[GeneratorFunction: function\*func\]/);

  cli.writeLine('exec a = function * func() {}; a;', true);
  await cli.waitFor(/\[GeneratorFunction\]/);
  await cli.waitForPrompt();
  assert.match(cli.output, /\[GeneratorFunction\]/);
} finally {
  cli.quit();
}
