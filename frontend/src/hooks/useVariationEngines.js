import { useEffect, useRef, useState } from 'react'
import { apiFetch } from '../api/fetchClient'
import { usePersistedPreference } from './usePersistedPreference'
import { resolveGeneratorSelection } from './variationEngineSelection.js'

/** Own persisted generator selection and settings/capability reconciliation. */
export function useVariationEngines(caps) {
  const hadStoredGenerator = useRef((() => {
    try { return globalThis.localStorage.getItem('datasetGenerator') !== null } catch { return false }
  })()).current
  const { value: generator, setValue: setGenerator } = usePersistedPreference(
    'datasetGenerator', 'klein', { parse: (value) => value || 'klein' },
  )
  const [enabledEngines, setEnabledEngines] = useState([])
  const [settingsLoaded, setSettingsLoaded] = useState(false)
  const [settingsError, setSettingsError] = useState(false)
  const [remoteAllowed, setRemoteAllowed] = useState(false)
  const [chatgptAuth, setChatgptAuth] = useState('auto')
  useEffect(() => {
    let cancelled = false
    apiFetch('/api/settings').then((data) => {
      if (cancelled) return
      const enabled = data.config?.engines?.enabled || []
      const configuredDefault = data.config?.engines?.default || 'klein'
      setEnabledEngines(enabled)
      setGenerator((current) => resolveGeneratorSelection(
        current, hadStoredGenerator, configuredDefault, enabled,
      ))
      setChatgptAuth(data.config?.engines?.chatgpt_auth || 'auto')
      setRemoteAllowed(!!data.config?.privacy?.allow_remote_generation)
      setSettingsLoaded(true); setSettingsError(false)
    }).catch(() => {
      if (!cancelled) { setSettingsLoaded(false); setSettingsError(true) }
    })
    return () => { cancelled = true }
  }, [hadStoredGenerator, setGenerator])
  const isNB = generator === 'nanobanana'
  const isGPT = generator === 'chatgpt'
  const isKlein = !isNB && !isGPT
  const nbAvailable = remoteAllowed && enabledEngines.includes('nanobanana') && caps.engines.nanobanana
  const gptAvailable = remoteAllowed && enabledEngines.includes('chatgpt') && caps.engines.chatgpt
  const klAvailable = enabledEngines.includes('klein') && caps.engines.klein
  const currentAvailable = settingsLoaded && (isKlein ? klAvailable : isNB ? nbAvailable : gptAvailable)
  const subscription = caps.chatgpt_subscription || {}
  const gptViaSub = chatgptAuth === 'subscription'
    || (chatgptAuth === 'auto' && !!subscription.connected)
  const gptPlanLabel = subscription.plan && subscription.plan !== 'free'
    ? subscription.plan.charAt(0).toUpperCase() + subscription.plan.slice(1) : 'Plus/Pro'
  const kleinHint = klAvailable ? null
    : !enabledEngines.includes('klein') ? '⚠ Klein is disabled in Settings (engines)'
    : !caps.comfyui?.reachable ? '⚠ Configure ComfyUI in Settings'
    : '⚠ Klein model missing — download it in the Setup step (models/unet/klein/)'
  return {
    generator, setGenerator, enabledEngines, settingsLoaded, settingsError, remoteAllowed,
    isNB, isGPT, isKlein, nbAvailable, gptAvailable, klAvailable,
    currentAvailable, gptViaSub, gptPlanLabel, kleinHint,
  }
}
