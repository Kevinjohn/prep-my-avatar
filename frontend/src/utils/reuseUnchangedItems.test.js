import assert from 'node:assert/strict';
import test from 'node:test';

import { reuseUnchangedItems } from './reuseUnchangedItems.js';

test('unchanged API rows retain their identities and array', () => {
  const previous = [
    { id: 2, caption: 'same', analysis: { score: 0.9 }, tags: ['a'] },
    { id: 1, caption: 'same', analysis: null, tags: [] },
  ];
  const incoming = structuredClone(previous);
  const result = reuseUnchangedItems(previous, incoming);
  assert.equal(result, previous);
  assert.equal(result[0], previous[0]);
  assert.equal(result[1], previous[1]);
});

test('changed and reordered API rows preserve only valid identities', () => {
  const previous = [
    { id: 2, caption: 'old', analysis: { score: 0.9 } },
    { id: 1, caption: 'same', analysis: null },
  ];
  const changed = { id: 2, caption: 'new', analysis: { score: 0.9 } };
  const result = reuseUnchangedItems(previous, [structuredClone(previous[1]), changed]);
  assert.notEqual(result, previous);
  assert.equal(result[0], previous[1]);
  assert.equal(result[1], changed);
});
