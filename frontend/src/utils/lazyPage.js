import { lazy } from 'react'

export const LAZY_PAGE_RELOAD_KEY = 'pma_stale_chunk_reloaded'

function browserStorage() {
  return window.sessionStorage
}

function browserReload() {
  window.location.reload()
}

export function loadLazyModule(importer, options = {}) {
  return Promise.resolve()
    .then(importer)
    .then((module) => {
      try {
        const storage = options.storage ?? browserStorage()
        storage.removeItem(LAZY_PAGE_RELOAD_KEY)
      } catch {
        // A successful import is usable even when private-mode storage is denied.
      }
      return module
    }, (error) => {
      let storage
      try {
        storage = options.storage ?? browserStorage()
        if (!storage || storage.getItem(LAZY_PAGE_RELOAD_KEY) === '1') {
          throw error
        }
        storage.setItem(LAZY_PAGE_RELOAD_KEY, '1')
      } catch {
        throw error
      }

      try {
        const reload = options.reload ?? browserReload
        reload()
      } catch {
        try { storage.removeItem(LAZY_PAGE_RELOAD_KEY) } catch { /* unavailable */ }
        throw error
      }
      return new Promise(() => {})
    })
}

export function lazyPage(importer) {
  return lazy(() => loadLazyModule(importer))
}
