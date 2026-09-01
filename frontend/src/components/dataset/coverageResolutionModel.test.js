import test from 'node:test';
import assert from 'node:assert/strict';
import { coverageResolution } from './coverageResolutionModel.js';

test('an older backend payload with framing gaps remains needs-attention', () => {
  const resolution = coverageResolution({
    summary: { gaps: 3, dimension_gaps: 5 },
    framing: [
      { framing: 'face', have: 8, target: 12, deficit: 4, state: 'weak' },
      { framing: 'bust', have: 17, target: 6, deficit: 0, state: 'covered' },
      { framing: 'body', have: 5, target: 6, deficit: 1, state: 'weak' },
      { framing: 'back', have: 0, target: 1, deficit: 1, state: 'missing' },
    ],
  });

  assert.equal(resolution.requiresAttention, true);
  assert.equal(resolution.unresolved, 8);
  assert.deepEqual(resolution.actions.map((item) => item.framing), ['back', 'face', 'body']);
});

test('a gap-free older backend payload remains complete', () => {
  const resolution = coverageResolution({
    summary: { gaps: 0, dimension_gaps: 0 },
    framing: [{ framing: 'face', have: 12, target: 12, deficit: 0, state: 'covered' }],
  });

  assert.equal(resolution.requiresAttention, false);
  assert.deepEqual(resolution.actions, []);
});
