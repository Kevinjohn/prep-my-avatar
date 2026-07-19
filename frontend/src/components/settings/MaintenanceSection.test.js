import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('./MaintenanceSection.jsx', import.meta.url), 'utf8');

test('empty trash reloads retained entries and reports partial failures', () => {
  const emptyHandler = source.slice(source.indexOf('const empty = async'), source.indexOf('const restore = async'));
  assert.match(emptyHandler, /await load\(\)/);
  assert.match(emptyHandler, /if \(d\?\.failed\)/);
  assert.doesNotMatch(emptyHandler, /setEntries\(\[\]\)/);
});
