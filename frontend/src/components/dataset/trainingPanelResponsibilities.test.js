import test from 'node:test';
import assert from 'node:assert/strict';

import { parseTrainingPreset, MAX_PRESET_BYTES,
  normalizeCheckpointPayload, checkpointsToKeep, nextContinueStep } from './trainingPanelResponsibilities.js';

test('training preset parser accepts only the versioned object contract', () => {
  const preset = parseTrainingPreset(JSON.stringify({
    kind: 'training-preset', version: 1, name: 'Portrait',
    train_type: 'zimage', settings: { rank: 16 },
  }));
  assert.equal(preset.settings.rank, 16);
  assert.throws(() => parseTrainingPreset(JSON.stringify({
    kind: 'training-preset', version: 2, name: 'Future', settings: {},
  })), /unsupported/);
  assert.equal(MAX_PRESET_BYTES, 256 * 1024);
});

test('checkpoint browser normalizes malformed collections and owns total count', () => {
  assert.deepEqual(normalizeCheckpointPayload({
    checkpoints: [{ step: 100 }], imported: null,
    cloud_checkpoints: [{ step: 200 }, { step: 300 }],
    dataset_state: { version: 4 }, disk_usage: { total_bytes: 9 },
  }), {
    checkpoints: [{ step: 100 }], imported: [],
    cloudCheckpoints: [{ step: 200 }, { step: 300 }],
    datasetState: { version: 4 }, diskUsage: { total_bytes: 9 }, count: 3,
  });
});

test('checkpoints-to-keep retains finals + best epoch, falling back to the last step', () => {
  const checkpoints = [
    { filename: 'step-100.safetensors', step: 100, final: false },
    { filename: 'step-200.safetensors', step: 200, final: false },
    { filename: 'final.safetensors', step: 300, final: true },
  ];
  assert.deepEqual(checkpointsToKeep(checkpoints, null), ['final.safetensors']);
  assert.deepEqual(
    checkpointsToKeep(checkpoints, { available: true, checkpoint: 'step-100.safetensors' }),
    ['final.safetensors', 'step-100.safetensors'],
  );
  // No final yet, no best epoch scored: keep the last step so the button
  // never proposes trashing the entire (unfinished) run.
  const unfinished = checkpoints.slice(0, 2);
  assert.deepEqual(checkpointsToKeep(unfinished, null), ['step-200.safetensors']);
  // Genuinely empty: nothing to keep.
  assert.deepEqual(checkpointsToKeep([], null), []);
});

test('next-continue-step is the highest step among the run\'s checkpoints', () => {
  assert.equal(nextContinueStep([{ step: 100 }, { step: 300 }, { step: 200 }]), 300);
  assert.equal(nextContinueStep([{ step: 50 }]), 50);
  // Guarded call site: the Continue-training button only renders when
  // checkpoints.length > 0, so the empty-list case (-Infinity) is unreached
  // in practice — documented here to match, not "fixed".
  assert.equal(nextContinueStep([]), -Infinity);
});
