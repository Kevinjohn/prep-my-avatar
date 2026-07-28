import assert from 'node:assert/strict'
import test from 'node:test'
import { deriveCloudTrainingState } from './trainingCloudState.js'

const base = {
  cloudStatus: { limit: 2, actives: [] }, datasetId: 7, trainType: 'zimage',
  keptCount: 10, preflightFloor: 5, typeLabel: 'Z-Image', customBase: false,
  vaePath: '', tePath: '', hasInvalidStepsOverride: false,
  stepsOverrideValid: true, launchConfigReady: true,
}

test('cloud training state supports legacy active envelopes and family isolation', () => {
  const run = { dataset_id: 7, train_type: 'zimage' }
  const state = deriveCloudTrainingState({ ...base, cloudStatus: { limit: 2, active: run } })
  assert.deepEqual(state.actives, [run])
  assert.equal(state.cloudActiveHere, run)
  assert.match(state.cloudDisabledReason, /already active/)
  const otherFamily = deriveCloudTrainingState({
    ...base, cloudStatus: { limit: 2, actives: [{ ...run, train_type: 'krea' }] },
  })
  assert.equal(otherFamily.cloudActiveHere, undefined)
  assert.equal(otherFamily.cloudDisabledReason, null)
})

test('cloud block reason prioritizes unsupported family, invalid config, floor, then limit', () => {
  assert.match(deriveCloudTrainingState({ ...base, trainType: 'sdxl' }).cloudDisabledReason, /locally only/)
  assert.match(deriveCloudTrainingState({ ...base, stepsOverrideValid: false }).cloudDisabledReason, /whole number/)
  assert.match(deriveCloudTrainingState({ ...base, keptCount: 1 }).cloudDisabledReason, /Only 1 image/)
  assert.match(deriveCloudTrainingState({
    ...base, cloudStatus: { limit: 1, actives: [{ dataset_id: 99 }] },
  }).cloudDisabledReason, /limit reached/)
})
