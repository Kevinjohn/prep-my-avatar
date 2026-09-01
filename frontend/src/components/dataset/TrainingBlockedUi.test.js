import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const readiness = readFileSync(new URL('./TrainingReadiness.jsx', import.meta.url), 'utf8');
const panel = readFileSync(new URL('./TrainingPanel.jsx', import.meta.url), 'utf8');

test('collapsed readiness keeps the first blocking reason visible', () => {
  assert.match(readiness, /firstBlocker/);
  assert.match(readiness, /!open && firstBlocker/);
  assert.match(readiness, /role="alert"/);
  assert.match(readiness, /firstBlocker\.label/);
  assert.match(readiness, /firstBlocker\.detail/);
});

test('server preflight blockers disable every training launch path', () => {
  assert.match(panel, /preflightBlocker/);
  assert.match(panel, /launchConfigReady[\s\S]*?!preflightBlocker/);
  assert.match(panel, /preflightBlocker \? preflightBlocker/);
});
