import assert from 'node:assert/strict';
import test from 'node:test';

import { captionHasTag, filterImages } from './tagFilter.js';

test('tag matching normalizes canonically equivalent Unicode', () => {
  assert.equal(captionHasTag('café, portrait', 'cafe\u0301', 'booru'), true);
  assert.equal(captionHasTag('A cafe\u0301 portrait', 'café', 'prose'), true);
  assert.equal(captionHasTag('नमस्ते portrait', 'नमस्ते', 'prose'), true);
});

test('filterImages preserves include, exclude, empty-tag, and Unicode semantics', () => {
  const images = [
    { id: 1, caption: 'A cafe\u0301 portrait with a warm smile.' },
    { id: 2, caption: 'café, smiling, portrait' },
    { id: 3, caption: '' },
  ];
  assert.deepEqual(
    filterImages(images, { mode: 'prose', includes: ['café'], excludes: ['smile', ''] })
      .map((image) => image.id),
    [2],
  );
  assert.deepEqual(
    filterImages(images, { mode: 'booru', includes: ['portrait'], excludes: ['smile'] })
      .map((image) => image.id),
    [2],
  );
  assert.equal(filterImages(images, {}), images);
  assert.deepEqual(filterImages(images, { includes: [''] }), []);
});
