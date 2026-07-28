import { useCallback, useState } from 'react'
import { loadCustomShots, loadShotPresets, persistCustomShots, persistShotPresets } from '../utils/shotPresets'

/** Owns recoverable browser persistence for user-authored shots and presets. */
export function useShotPersistence(toast, storage = globalThis.localStorage) {
  const [customShots, setCustomShots] = useState(() => loadCustomShots(storage))
  const [customPresets, setCustomPresets] = useState(() => loadShotPresets(storage))
  const [storageWarning, setStorageWarning] = useState(false)
  const commitCustomShots = useCallback((next) => {
    setCustomShots(next)
    try { persistCustomShots(storage, next); setStorageWarning(false); return true }
    catch {
      setStorageWarning(true)
      toast.error('Custom shots are session-only because browser storage is unavailable. Copy any important prompts before reloading.')
      return false
    }
  }, [storage, toast])
  const commitCustomPresets = useCallback((next, successMessage = '') => {
    setCustomPresets(next)
    try {
      persistShotPresets(storage, next); setStorageWarning(false)
      if (successMessage) toast.success(successMessage)
      return true
    } catch {
      setStorageWarning(true)
      toast.error('Preset is session-only because browser storage is unavailable. Free browser storage and save it again before reloading.')
      return false
    }
  }, [storage, toast])
  return { customShots, customPresets, storageWarning, commitCustomShots, commitCustomPresets }
}
