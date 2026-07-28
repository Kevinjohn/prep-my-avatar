import assert from 'node:assert/strict';
import test from 'node:test';

import { captionHasTag } from './tagFilter.js';

test('tag matching normalizes canonically equivalent Unicode', () => {
  assert.equal(captionHasTag('café, portrait', 'cafe\u0301', 'booru'), true);
  assert.equal(captionHasTag('A cafe\u0301 portrait', 'café', 'prose'), true);
  assert.equal(captionHasTag('नमस्ते portrait', 'नमस्ते', 'prose'), true);
});
