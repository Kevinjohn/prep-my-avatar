import test from 'node:test';
import assert from 'node:assert/strict';

import { buildImageImprovementPairs, filterImageImprovementGrid } from './imageImprovement.js';

test('unresolved reconstruction pair stays out of generic curation', () => {
  const rows = [
    { id: 1, status: 'keep', filename: 'source.webp' },
    { id: 2, status: 'pending', filename: 'candidate.webp', parent_image_id: 1,
      derivation_kind: 'klein_image_improve' },
    { id: 3, status: 'keep', filename: 'ordinary.webp' },
  ];
  const pairs = buildImageImprovementPairs(rows);
  assert.equal(pairs.length, 1);
  assert.equal(pairs[0].resolved, false);
  assert.deepEqual(filterImageImprovementGrid(rows).map((row) => row.id), [3]);
});

test('resolved reconstruction pair exposes exactly its admitted winner', () => {
  const sourceWinner = [
    { id: 1, status: 'keep', filename: 'source.webp' },
    { id: 2, status: 'reject', filename: 'candidate.webp', parent_image_id: 1,
      derivation_kind: 'klein_image_improve' },
  ];
  assert.deepEqual(filterImageImprovementGrid(sourceWinner).map((row) => row.id), [1]);

  const candidateWinner = [
    { id: 1, status: 'reject', filename: 'source.webp' },
    { id: 2, status: 'keep', filename: 'candidate.webp', parent_image_id: 1,
      derivation_kind: 'klein_image_improve' },
  ];
  assert.deepEqual(filterImageImprovementGrid(candidateWinner).map((row) => row.id), [2]);
});

test('legacy siblings form one exclusive group and expose only the kept winner', () => {
  const unresolved = [
    { id: 1, status: 'pending', filename: 'source.webp' },
    { id: 2, status: 'keep', filename: 'old.webp', parent_image_id: 1,
      derivation_kind: 'klein_image_improve' },
    { id: 3, status: 'pending', filename: 'new.webp', parent_image_id: 1,
      derivation_kind: 'klein_image_improve' },
  ];
  const pairs = buildImageImprovementPairs(unresolved);
  assert.equal(pairs.length, 1);
  assert.deepEqual(pairs[0].imageIds, [1, 2, 3]);
  assert.equal(pairs[0].resolved, false);
  assert.deepEqual(filterImageImprovementGrid(unresolved), []);

  const resolved = unresolved.map((row) => ({ ...row,
    status: row.id === 1 ? 'reject' : row.id === 2 ? 'keep' : 'reject' }));
  assert.deepEqual(filterImageImprovementGrid(resolved).map((row) => row.id), [2]);
});

test('orphaned legacy reconstruction remains available for ordinary cleanup', () => {
  const orphan = { id: 8, status: 'reject', filename: 'orphan.webp', parent_image_id: 99,
    derivation_kind: 'klein_image_improve' };
  assert.deepEqual(buildImageImprovementPairs([orphan]), []);
  assert.deepEqual(filterImageImprovementGrid([orphan]), [orphan]);
});
