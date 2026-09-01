import test from 'node:test'
import assert from 'node:assert/strict'
import { applyRemoteIdentityCanary } from './variationLaunch.js'

const variations = [
  { id: 'face', label: 'Face' },
  { id: 'body', label: 'Body' },
]

test('an unverified remote engine launches exactly one identity canary', () => {
  const plan = applyRemoteIdentityCanary({
    variations, multiplier: 3, images: [], engine: 'nanobanana', isKlein: false,
  })

  assert.equal(plan.canary, true)
  assert.equal(plan.requestedTotal, 6)
  assert.equal(plan.multiplier, 1)
  assert.deepEqual(plan.variations, [variations[0]])
})

test('a kept image from the same remote engine unlocks the requested batch', () => {
  const plan = applyRemoteIdentityCanary({
    variations,
    multiplier: 2,
    engine: 'chatgpt',
    isKlein: false,
    images: [
      { source: 'generated', status: 'keep', generation_engine: 'nanobanana' },
      { source: 'generated', status: 'keep', generation_engine: 'chatgpt' },
    ],
  })

  assert.equal(plan.canary, false)
  assert.equal(plan.requestedTotal, 4)
  assert.equal(plan.multiplier, 2)
  assert.deepEqual(plan.variations, variations)
})

test('rejected and pending outputs never count as identity approval', () => {
  const plan = applyRemoteIdentityCanary({
    variations,
    multiplier: 1,
    engine: 'nanobanana',
    isKlein: false,
    images: [
      { source: 'generated', status: 'reject', generation_engine: 'nanobanana' },
      { source: 'generated', status: 'pending', generation_engine: 'nanobanana' },
    ],
  })

  assert.equal(plan.canary, true)
  assert.deepEqual(plan.variations, [variations[0]])
})

test('local Klein runs are never canary-limited', () => {
  const plan = applyRemoteIdentityCanary({
    variations, multiplier: 3, images: [], engine: 'klein', isKlein: true,
  })

  assert.equal(plan.canary, false)
  assert.equal(plan.multiplier, 3)
  assert.deepEqual(plan.variations, variations)
})
