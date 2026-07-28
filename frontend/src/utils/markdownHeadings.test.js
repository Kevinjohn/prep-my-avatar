import test from 'node:test';
import assert from 'node:assert/strict';

import { markdownHeadingIds, markdownHeadingModel } from './markdownHeadings.js';

test('heading ids are Unicode-aware, nonempty, and unique', () => {
  assert.deepEqual(
    markdownHeadingIds(['Same', 'Same', 'Café déjà', '日本語', '!!!', '???']),
    ['same', 'same-2', 'café-déjà', '日本語', 'section', 'section-2'],
  );
});

test('guide heading model shares ids with rendered headings', () => {
  assert.deepEqual(markdownHeadingModel('# Guide\n\n## **Same**\n\n## Same'), [
    { title: 'Same', id: 'same' },
    { title: 'Same', id: 'same-2' },
  ]);
});
