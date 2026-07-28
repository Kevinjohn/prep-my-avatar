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

test('maintenance fetch failures have persistent, accessible retry states', () => {
  const logViewer = source.slice(source.indexOf('function LogViewer'), source.indexOf('function TrashCard'));
  const trashCard = source.slice(source.indexOf('function TrashCard'), source.indexOf('function IntegrityCard'));

  assert.match(logViewer, /setError\(loadError\?\.message/);
  assert.match(logViewer, /role="alert"/);
  assert.match(logViewer, /onClick=\{load\}/);
  assert.match(logViewer, /Log data is unavailable\./);
  assert.match(trashCard, /setLoadError\(error\?\.message/);
  assert.match(trashCard, /Trash inventory unavailable/);
  assert.match(trashCard, /onClick=\{load\}/);
});

test('successful trash mutations remain successful when inventory refresh fails', () => {
  const emptyHandler = source.slice(source.indexOf('const empty = async'), source.indexOf('const restore = async'));
  const restoreHandler = source.slice(source.indexOf('const restore = async'), source.indexOf('return (', source.indexOf('const restore = async')));

  assert.match(emptyHandler, /setMessage\(outcome\)[\s\S]*if \(!\(await load\(\)\)\)/);
  assert.match(emptyHandler, /Trash operation completed[^\n]+inventory could not be refreshed/);
  assert.match(restoreHandler, /setMessage\(d\.kind[\s\S]*if \(!\(await load\(\)\)\)/);
  assert.match(restoreHandler, /Item restored — inventory could not be refreshed/);
});

test('log clipboard feedback awaits both successful and rejected writes', () => {
  const logViewer = source.slice(source.indexOf('function LogViewer'), source.indexOf('function TrashCard'));
  const copyStart = logViewer.indexOf('const copy = async');
  const copyHandler = logViewer.slice(copyStart, logViewer.indexOf('\n  return (', copyStart));

  assert.match(copyHandler, /await navigator\.clipboard\.writeText/);
  assert.match(copyHandler, /Log copied to clipboard/);
  assert.match(copyHandler, /Could not copy the log/);
  assert.match(logViewer, /copyStatus && <p role="status"/);
});
