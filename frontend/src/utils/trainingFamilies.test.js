import test from 'node:test';
import assert from 'node:assert/strict';

import { TRAINING_FAMILY_LABELS } from './trainingFamilies.js';

test('training family labels cover the supported codes', () => {
  assert.deepEqual(TRAINING_FAMILY_LABELS, {
    zimage: 'Z-Image',
    sdxl: 'SDXL',
    krea: 'Krea 2',
    flux: 'FLUX.1',
    flux2klein: 'FLUX.2 Klein',
  });
});
