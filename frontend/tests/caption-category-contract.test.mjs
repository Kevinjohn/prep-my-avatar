import assert from 'node:assert/strict'
import test from 'node:test'

import {
  captionCategoryCopy,
  captionFrequencyEntries,
  recaptionConfirmation,
} from '../src/components/dataset/captionCategory.js'

test('prose frequency counts useful words by caption instead of comma fragments', () => {
  const entries = captionFrequencyEntries([
    'A woman wearing a red dress, standing in a studio.',
    'A man in a red jacket standing outdoors.',
    'Red fabric fills the frame.',
  ], 'prose')
  assert.deepEqual(entries.slice(0, 2), [['red', 3], ['standing', 2]])
  assert.equal(entries.some(([term]) => term.includes('woman wearing')), false)
})

test('booru frequency keeps exact comma-separated tags', () => {
  assert.deepEqual(captionFrequencyEntries([
    'red dress, standing, studio',
    'red dress, outdoors',
  ], 'booru').slice(0, 2), [['red dress', 2], ['outdoors', 1]])
})

test('caption guidance is specific to character, concept and style datasets', () => {
  const character = captionCategoryCopy('character', 'prose')
  const concept = captionCategoryCopy('concept', 'prose')
  const style = captionCategoryCopy('style', 'prose')

  assert.match(character.frequencyHelp, /identity|character/i)
  assert.match(concept.frequencyHelp, /concept.*leak|leak check/i)
  assert.match(style.frequencyHelp, /style LoRA|aesthetic/i)
  assert.doesNotMatch(style.frequencyHelp, /your trigger/i)
  assert.equal(style.leakSummary, 'Aesthetic terms should stay out of captions')
})

test('re-caption confirmation explains the correct category rule', () => {
  const counts = {
    blank: 1, machine: 2, asserted: 1, unrecorded: 1, unknown: 1,
    rewrite: 5, spared: 1, rewriteWithAsserted: 6,
  }
  const ordinary = recaptionConfirmation('character', counts)
  assert.match(ordinary, /2 machine-written/i)
  assert.match(ordinary, /1 author-not-recorded/i)
  assert.match(ordinary, /1 unknown-origin/i)
  assert.match(ordinary, /1 blank/i)
  assert.match(ordinary, /spare the 1 caption you wrote/i)
  assert.match(ordinary, /identity/i)
  assert.match(recaptionConfirmation('concept', counts), /concept/i)
  assert.match(recaptionConfirmation('style', counts), /style|aesthetic/i)

  const override = recaptionConfirmation('character', counts, true)
  assert.match(override, /also replace the 1 caption you wrote/i)
  assert.doesNotMatch(override, /spare the 1 caption/i)
})
