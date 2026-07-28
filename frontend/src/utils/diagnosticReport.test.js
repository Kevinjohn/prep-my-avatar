import test from 'node:test';
import assert from 'node:assert/strict';
import { formatDiagnostic } from './diagnosticReport.js';

test('diagnostic report chooses a fence longer than backtick runs in logs', () => {
  const output = formatDiagnostic({
    app_version: '1', os: 'test', python: '3', capabilities: {}, config: {},
    log_tail: ['ordinary', '``` nested', '```` longer'], secrets_present: {},
  });
  const [opening, ...rest] = output.split('\n');
  assert.equal(opening, '`````');
  assert.equal(rest.at(-1), opening);
  assert.match(output, /```` longer/);
});
