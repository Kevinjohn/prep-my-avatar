import test from 'node:test';
import assert from 'node:assert/strict';
import { decodeStudioForm, groupStudioRuns } from './studioState.js';

test('decodeStudioForm drops malformed persisted field shapes and ranges', () => {
  assert.deepEqual(decodeStudioForm({ selCps: {}, selSts: [0.7], seed: -1,
    seedLocked: 'yes', genCount: 99, promptText: 42 }), { selSts: [0.7] });
  assert.deepEqual(decodeStudioForm(null), {});
});

test('groupStudioRuns keeps launches distinct even with the same prompt and seed', () => {
  const runs = groupStudioRuns([
    { id: 1, run_id: 'a', run_seed: 7, prompt: 'portrait' },
    { id: 2, run_id: 'b', run_seed: 7, prompt: 'portrait' },
  ]);
  assert.equal(runs.length, 2);
  assert.deepEqual(runs.map((run) => run.cells.map((cell) => cell.id)), [[2], [1]]);
});

test('groupStudioRuns retains the seed/prompt fallback for legacy rows', () => {
  assert.equal(groupStudioRuns([
    { id: 1, run_seed: 7, prompt: 'portrait' },
    { id: 2, run_seed: 7, prompt: 'portrait' },
  ]).length, 1);
});
