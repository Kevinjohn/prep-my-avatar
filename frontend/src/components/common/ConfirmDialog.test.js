import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('./ConfirmDialog.jsx', import.meta.url), 'utf8');

test('queued dialogs remount with request-local form state', () => {
  assert.match(source, /id: \+\+requestSequenceRef\.current/g);
  assert.match(source, /<PromptDialog key=\{active\.id\}/);
});
