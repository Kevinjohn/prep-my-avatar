import { useEffect } from 'react'

const WARNING = 'You have unsaved changes. Leave this page and discard them?'

let activeGuard = null
let acceptedHash = ''
let allowedHash = null
let restoring = false
let installed = false

const routeFromHash = (hash) => (hash.startsWith('#') ? hash.slice(1) : hash) || '/'

export function shouldBlockHashNavigation(fromHash, toHash, scope) {
  const from = routeFromHash(fromHash)
  const to = routeFromHash(toHash)
  if (from === to) return false
  if (scope === 'settings' && from.startsWith('/settings') && to.startsWith('/settings')) return false
  return true
}

/** Install before HashRouter mounts. Owning history interception outside the
 * route tree prevents a transition from unmounting its own dirty-page guard. */
export function installUnsavedChangesGuard() {
  if (installed || typeof window === 'undefined') return
  installed = true
  acceptedHash = window.location.hash

  window.addEventListener('beforeunload', (event) => {
    if (!activeGuard) return
    event.preventDefault()
    event.returnValue = ''
  })
  document.addEventListener('click', (event) => {
    if (!activeGuard || event.defaultPrevented || event.button !== 0 || event.metaKey
        || event.ctrlKey || event.shiftKey || event.altKey) return
    const found = event.target instanceof Element ? event.target.closest('a[href]') : null
    const anchor = found instanceof HTMLAnchorElement ? found : null
    if (!anchor || anchor.target === '_blank' || anchor.hasAttribute('download')) return
    const target = new URL(anchor.href, window.location.href)
    if (target.origin !== window.location.origin
        || !shouldBlockHashNavigation(window.location.hash, target.hash, activeGuard.scope)) return
    if (!window.confirm(WARNING)) {
      event.preventDefault()
      event.stopPropagation()
      return
    }
    allowedHash = target.hash
  }, true)
  const handleHistoryChange = () => {
    const next = window.location.hash
    if (restoring) {
      restoring = false
      return
    }
    if (!activeGuard) {
      acceptedHash = next
      return
    }
    if (allowedHash === next) {
      allowedHash = null
      acceptedHash = next
      return
    }
    if (!shouldBlockHashNavigation(acceptedHash, next, activeGuard.scope)
        || window.confirm(WARNING)) {
      acceptedHash = next
      return
    }
    restoring = true
    window.location.hash = acceptedHash
  }
  // Browsers dispatch popstate before hashchange for back/forward traversal.
  // Register both: the earlier event restores before HashRouter can unmount the
  // dirty page, while the second becomes a no-op against the accepted hash.
  window.addEventListener('popstate', handleHistoryChange)
  window.addEventListener('hashchange', handleHistoryChange)
}

/** Register one page's dirty state with the app-wide navigation owner. */
export function useUnsavedChangesGuard(dirty, scope) {
  useEffect(() => {
    if (!dirty) return undefined
    const registration = { scope }
    activeGuard = registration
    acceptedHash = window.location.hash
    return () => {
      if (activeGuard === registration) activeGuard = null
    }
  }, [dirty, scope])
}
