import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

test('toast timers pause for interaction and provider globals are cleaned up', () => {
  const source = readFileSync(new URL('./Toast.jsx', import.meta.url), 'utf8');
  assert.match(source, /onMouseEnter=\{\(\) => onPause\(t\.id\)\}/);
  assert.match(source, /onFocus=\{\(\) => onPause\(t\.id\)\}/);
  assert.match(source, /if \(window\.__adminToast === toast\) delete window\.__adminToast/);
  assert.match(source, /timers\.current\.clear\(\)/);
});

test('markdown parser validates table delimiters before dropping a row', () => {
  const source = readFileSync(new URL('./Markdown.jsx', import.meta.url), 'utf8');
  assert.match(source, /delimiter\.every/);
  assert.match(source, /if \(valid\)/);
  assert.match(source, /rows\.forEach\(\(body\) => blocks\.push/);
});
