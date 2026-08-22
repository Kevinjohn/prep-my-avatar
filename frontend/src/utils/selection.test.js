import assert from 'node:assert/strict';
import test from 'node:test';

import { toggleInSet } from './selection.js';

test('toggleInSet adds an absent value without mutating the input Set', () => {
  const current = new Set(['existing']);

  const next = toggleInSet(current, 'added');

  assert.deepEqual(next, new Set(['existing', 'added']));
  assert.deepEqual(current, new Set(['existing']));
  assert.notEqual(next, current);
});

test('toggleInSet removes a present value without mutating the input Set', () => {
  const current = new Set(['existing', 'removed']);

  const next = toggleInSet(current, 'removed');

  assert.deepEqual(next, new Set(['existing']));
  assert.deepEqual(current, new Set(['existing', 'removed']));
  assert.notEqual(next, current);
});
