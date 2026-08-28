import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { LAZY_PAGE_RELOAD_KEY, loadLazyModule } from './lazyPage.js'

function memoryStorage(initial = []) {
  const values = new Map(initial)
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
    values,
  }
}

test('successful import returns its module and clears the reload guard', async () => {
  const storage = memoryStorage([[LAZY_PAGE_RELOAD_KEY, '1']])
  const module = { default: () => null }

  assert.equal(
    await loadLazyModule(() => Promise.resolve(module), { storage, reload: () => {} }),
    module,
  )
  assert.equal(storage.values.has(LAZY_PAGE_RELOAD_KEY), false)
})

test('first failed import records the guard and reloads exactly once', async () => {
  const storage = memoryStorage()
  const error = new Error('stale chunk')
  let reloads = 0
  let settled = false

  loadLazyModule(
    () => Promise.reject(error),
    { storage, reload: () => { reloads += 1 } },
  ).finally(() => { settled = true })
  await new Promise((resolve) => setImmediate(resolve))

  assert.equal(storage.values.get(LAZY_PAGE_RELOAD_KEY), '1')
  assert.equal(reloads, 1)
  assert.equal(settled, false)
})

test('second failed import rethrows the original error without reloading', async () => {
  const storage = memoryStorage([[LAZY_PAGE_RELOAD_KEY, '1']])
  const error = new Error('chunk is genuinely missing')
  let reloads = 0

  await assert.rejects(
    loadLazyModule(
      () => Promise.reject(error),
      { storage, reload: () => { reloads += 1 } },
    ),
    (caught) => caught === error,
  )
  assert.equal(reloads, 0)
})

test('denied storage rethrows the import error instead of risking a loop', async () => {
  const denied = () => { throw new DOMException('denied', 'SecurityError') }
  const storage = { getItem: denied, setItem: denied, removeItem: denied }
  const error = new Error('chunk load failed')
  let reloads = 0

  await assert.rejects(
    loadLazyModule(
      () => Promise.reject(error),
      { storage, reload: () => { reloads += 1 } },
    ),
    (caught) => caught === error,
  )
  assert.equal(reloads, 0)
})

test('successful imports still resolve when clearing storage is denied', async () => {
  const denied = () => { throw new DOMException('denied', 'SecurityError') }
  const module = { default: () => null }

  assert.equal(
    await loadLazyModule(
      () => Promise.resolve(module),
      { storage: { removeItem: denied }, reload: () => {} },
    ),
    module,
  )
})

test('every routed page uses one-shot lazy recovery', () => {
  const app = readFileSync(new URL('../App.jsx', import.meta.url), 'utf8')
  const pages = [
    'DatasetPage',
    'StudioPage',
    'SettingsPage',
    'SetupPage',
    'GuidePage',
    'CloudRunsPage',
  ]

  for (const page of pages) {
    assert.match(app, new RegExp(`const ${page} = lazyPage\\(`))
  }
  assert.doesNotMatch(app, /\blazy\(/)
})
