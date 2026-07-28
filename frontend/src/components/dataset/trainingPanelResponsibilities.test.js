import test from 'node:test';
import assert from 'node:assert/strict';

import { parseTrainingPreset, MAX_PRESET_BYTES,
  normalizeCheckpointPayload } from './trainingPanelResponsibilities.js';

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
