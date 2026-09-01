import assert from 'node:assert/strict'
import test from 'node:test'

import { coverageClassificationNotice } from './coverageClassification.js'

test('zero mapped photos is an actionable warning instead of a success', () => {
  assert.deepEqual(coverageClassificationNotice(0), {
    severity: 'warning',
    message: 'No photo details were added. Local vision is connected but returned no usable classifications. In Setup, make sure the loaded model supports images, then retry — or describe each photo manually here.',
  })
})

test('mapped photos retain the successful count', () => {
  assert.deepEqual(coverageClassificationNotice(12), {
    severity: 'success',
    message: '12 image(s) mapped for coverage',
  })
})
