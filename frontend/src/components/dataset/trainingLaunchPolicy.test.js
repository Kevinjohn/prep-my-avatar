import assert from 'node:assert/strict'
import test from 'node:test'
import { confirmableTrainingRefusal, parseTrainingSteps, trainingLaunchBody } from './trainingLaunchPolicy.js'

test('training step policy distinguishes adaptive, malformed, floor, and exact values', () => {
  assert.deepEqual(parseTrainingSteps(''), { valid: true, invalidFormat: false, steps: null })
  assert.equal(parseTrainingSteps('abc').invalidFormat, true)
  assert.equal(parseTrainingSteps('499').valid, false)
  assert.equal(parseTrainingSteps('500').steps, 500)
})

test('launch body snapshots fresh mode and family-only overrides', () => {
  const body = trainingLaunchBody({ base: 'b', variant: 'v', trainType: 'sdxl', masked: true,
    steps: 500, mode: 'fresh', vaePath: 'vae', tePath: 'te' }, { at: 'later' })
  assert.deepEqual(body, { at: 'later', base_model: 'b', variant: 'v', train_type: 'sdxl',
    masked: true, steps: 500, fresh: true, vae_path: 'vae', te_path: 'te' })
  assert.deepEqual(confirmableTrainingRefusal('UNCAPTIONED: 2 rows'), {
    message: '2 rows', flag: 'allow_uncaptioned',
  })
})
