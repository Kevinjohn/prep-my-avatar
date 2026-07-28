import assert from 'node:assert/strict'
import test from 'node:test'

import { tierDims } from './resolutionMetadata.js'

const metadata = {
  dimensions: {
    default: { square: { standard: [1008, 1008] }, tall: { standard: [752, 1344] } },
    sdxl: { square: { standard: [1008, 1008] }, tall: { standard: [576, 1024] } },
  },
}

test('resolution display selects exact backend-generated profile dimensions', () => {
  assert.deepEqual(tierDims(metadata, 'tall', 'standard'), [752, 1344])
  assert.deepEqual(tierDims(metadata, 'tall', 'standard', 1024), [576, 1024])
  assert.deepEqual(tierDims(metadata, 'unknown', 'standard'), [1008, 1008])
})
