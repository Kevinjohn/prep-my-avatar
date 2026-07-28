import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { buildVariationLaunch, partitionExistingShots } from '../src/components/dataset/variationLaunch.js'
import { LABELS, displayLabel } from '../src/utils/labels.js'

test('variation launch preflight filters unavailable and paid-lane shots without mutating selection', () => {
  const selected = new Set(['ordinary', 'adult', 'custom-safe', 'custom-adult'])
  const input = {
    catalog: [{ id: 'ordinary', label: 'Ordinary', prompt: 'a', framing: 'face' }],
    nsfwCatalog: [{ id: 'adult', label: 'Adult', prompt: 'b', framing: 'body' }],
    customShots: [
      { id: 'custom-safe', label: 'Safe', prompt: 'c', framing: 'bust' },
      { id: 'custom-adult', label: 'Hot', prompt: 'd', framing: 'body', nsfw: true },
    ], selected, nsfwMode: true,
  }
  assert.deepEqual(buildVariationLaunch({ ...input, isKlein: false }).map((item) => item.id),
    ['ordinary', 'custom-safe'])
  const klein = buildVariationLaunch({ ...input, isKlein: true })
  assert.deepEqual(klein.map((item) => item.id), [...selected])
  assert.equal(klein.find((item) => item.id === 'adult').nsfw, true)
  assert.deepEqual(partitionExistingShots(klein, new Map([['Ordinary', 1]])), {
    existing: [klein[0]], fresh: klein.slice(1),
  })
  assert.deepEqual([...selected], ['ordinary', 'adult', 'custom-safe', 'custom-adult'])
})

test('every generated backend catalog label has an explicit frontend display mapping', () => {
  const backend = readFileSync(new URL('../../backend/app/services/face_variations.py', import.meta.url), 'utf8')
  const quoted = "(?:\\\\'|[^'])+"
  const entry = new RegExp(`_e\\(\\s*'${quoted}'\\s*,\\s*'${quoted}'\\s*,\\s*'${quoted}'\\s*,\\s*'(${quoted})'`, 'g')
  const labels = [...backend.matchAll(entry)].map((match) => match[1].replaceAll("\\'", "'"))
  assert.ok(labels.length > 50, 'fixture must cover both generated catalogs')
  assert.deepEqual(labels.filter((label) => !Object.hasOwn(LABELS, label)), [])
  for (const label of labels) assert.notEqual(displayLabel(label), label)
})
