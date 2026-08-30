import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('./DatasetWorkflowNav.jsx', import.meta.url), 'utf8');

test('step navigator exposes semantic current-step and textual status information', () => {
  assert.match(source, /aria-label="Dataset steps"/);
  assert.match(source, /aria-current=\{current \? 'step'/);
  assert.match(source, /Complete/);
  assert.match(source, /Optional/);
  assert.match(source, /Unavailable/);
  assert.match(source, /step\.unavailableReason/);
});

test('step actions include previous, continue, and explicit optional skip controls', () => {
  assert.match(source, /aria-label="Step actions"/);
  assert.match(source, /← Back/);
  assert.match(source, /Skip optional step/);
  assert.match(source, /Continue/);
  assert.match(source, /current\.optional && next/);
});
