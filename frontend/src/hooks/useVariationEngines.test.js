import assert from 'node:assert/strict'
import test from 'node:test'

import { resolveGeneratorSelection } from './variationEngineSelection.js'

test('configured default is selected when no browser preference exists', () => {
  assert.equal(resolveGeneratorSelection(
    'klein', false, 'chatgpt', ['klein', 'chatgpt'],
  ), 'chatgpt')
})

test('an enabled browser preference remains explicit', () => {
  assert.equal(resolveGeneratorSelection(
    'nanobanana', true, 'chatgpt', ['klein', 'nanobanana', 'chatgpt'],
  ), 'nanobanana')
})

test('a stale browser preference repairs to the configured default', () => {
  assert.equal(resolveGeneratorSelection(
    'nanobanana', true, 'chatgpt', ['klein', 'chatgpt'],
  ), 'chatgpt')
})

test('remote defaults remain selected even before privacy consent is enabled', () => {
  assert.equal(resolveGeneratorSelection(
    'klein', false, 'chatgpt', ['klein', 'chatgpt'],
  ), 'chatgpt')
})
