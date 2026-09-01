import assert from 'node:assert/strict';
import test from 'node:test';
import {
  TRAINING_FAMILY_REQUIREMENTS,
  TRAINING_LAUNCH_REQUIREMENTS,
} from './trainingSetupRequirements.js';

test('setup discloses prerequisites for every supported training family', () => {
  assert.deepEqual(
    TRAINING_FAMILY_REQUIREMENTS.map((item) => item.id),
    ['zimage', 'sdxl', 'krea', 'flux', 'flux2klein'],
  );
  assert.equal(
    TRAINING_FAMILY_REQUIREMENTS.find((item) => item.id === 'sdxl').needsComfyCheckpoint,
    true,
  );
  for (const family of ['krea', 'flux', 'flux2klein']) {
    const requirement = TRAINING_FAMILY_REQUIREMENTS.find((item) => item.id === family);
    assert.equal(requirement.needsHfToken, true);
    assert.ok(requirement.licenseLinks.length >= 1);
  }
  assert.equal(
    TRAINING_FAMILY_REQUIREMENTS.find((item) => item.id === 'zimage').needsHfToken,
    false,
  );
});

test('setup distinguishes launch-time gates from installation readiness', () => {
  const ids = TRAINING_LAUNCH_REQUIREMENTS.map((item) => item.id);
  for (const required of [
    'disk', 'active_run', 'toolkit_family', 'dataset_admission',
    'captions', 'custom_weights', 'trigger_collision',
  ]) assert.ok(ids.includes(required), `missing ${required}`);
});
