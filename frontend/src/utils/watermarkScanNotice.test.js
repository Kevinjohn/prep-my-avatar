import assert from 'node:assert/strict'
import test from 'node:test'

import { watermarkScanNotice } from './watermarkScanNotice.js'

test('zero checked photos is an actionable warning instead of a clean success', () => {
  assert.deepEqual(watermarkScanNotice({ checked: 0, detected: 0, none: 0 }), {
    severity: 'warning',
    message: 'No photos were checked for watermarks. Local vision returned no usable results, so this is not a clean scan. In Setup, verify the loaded model supports images, then retry.',
  })
})

test('checked photos retain the successful summary', () => {
  assert.deepEqual(watermarkScanNotice({ checked: 30, detected: 2, none: 28 }), {
    severity: 'success',
    message: '2 watermark(s) found · 28 clean (of 30)',
  })
})
