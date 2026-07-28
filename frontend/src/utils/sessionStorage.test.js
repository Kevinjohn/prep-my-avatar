import assert from 'node:assert/strict'
import test from 'node:test'

import { readSession, removeSession, writeSession } from './sessionStorage.js'

function withStorage(storage, callback) {
  const previous = globalThis.window
  globalThis.window = { sessionStorage: storage }
  try {
    callback()
  } finally {
    globalThis.window = previous
  }
}

test('session helpers preserve ordinary browser storage behavior', () => {
  const values = new Map()
  withStorage({
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  }, () => {
    assert.equal(readSession('seen'), null)
    assert.equal(writeSession('seen', '1'), true)
    assert.equal(readSession('seen'), '1')
    assert.equal(removeSession('seen'), true)
    assert.equal(readSession('seen'), null)
  })
})

test('session helpers contain denied reads and writes', () => {
  const denied = () => { throw new DOMException('denied', 'SecurityError') }
  withStorage({ getItem: denied, setItem: denied, removeItem: denied }, () => {
    assert.equal(readSession('seen'), null)
    assert.equal(writeSession('seen', '1'), false)
    assert.equal(removeSession('seen'), false)
  })
})
