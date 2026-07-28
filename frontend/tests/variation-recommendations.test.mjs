import assert from 'node:assert/strict';
import test from 'node:test';

import { initialVariationSelection } from '../src/components/dataset/variationRecommendations.js';

const presets = { balanced_25: ['balanced'], body_emphasis: ['body'] };

test('only undefined recommendations use a preset default', () => {
  assert.deepEqual(initialVariationSelection(presets, false, undefined), ['balanced']);
  assert.deepEqual(initialVariationSelection(presets, true, undefined), ['body']);
  assert.deepEqual(initialVariationSelection(presets, false, ['gap']), ['gap']);
  assert.deepEqual(initialVariationSelection(presets, false, []), []);
});
