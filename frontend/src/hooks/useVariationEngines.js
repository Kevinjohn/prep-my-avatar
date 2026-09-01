import { useEffect, useRef, useState } from 'react'
import { apiFetch, putJson } from '../api/fetchClient'
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
  const [nanoBananaProvider, setNanoBananaProvider] = useState('google')
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
      setNanoBananaProvider(data.config?.engines?.nanobanana_provider || 'google')
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
  const nbProviderReady = enabledEngines.includes('nanobanana') && caps.engines.nanobanana
  const gptProviderReady = enabledEngines.includes('chatgpt') && caps.engines.chatgpt
  const nbAvailable = remoteAllowed && nbProviderReady
  const gptAvailable = remoteAllowed && gptProviderReady
  const klAvailable = enabledEngines.includes('klein') && caps.engines.klein
  const currentAvailable = settingsLoaded && (
    isKlein ? klAvailable : isNB ? nbProviderReady : gptProviderReady
  )
  const subscription = caps.chatgpt_subscription || {}
  const gptViaSub = chatgptAuth === 'subscription'
    || (chatgptAuth === 'auto' && !!subscription.connected)
  const gptPlanLabel = subscription.plan && subscription.plan !== 'free'
    ? subscription.plan.charAt(0).toUpperCase() + subscription.plan.slice(1) : 'Plus/Pro'
  const nanoBananaProviderLabel = nanoBananaProvider === 'replicate' ? 'Replicate' : 'Google'
  const approveRemoteGeneration = async () => {
    if (remoteAllowed) return
    await putJson('/api/settings', {
      config: { privacy: { allow_remote_generation: true } },
    })
    setRemoteAllowed(true)
  }
  const kleinHint = klAvailable ? null
    : !enabledEngines.includes('klein') ? '⚠ Klein is disabled in Settings (engines)'
    : !caps.comfyui?.reachable ? '⚠ Configure ComfyUI in Settings'
    : '⚠ Klein model missing — download it in the Setup step (models/unet/klein/)'
  return {
    generator, setGenerator, enabledEngines, settingsLoaded, settingsError, remoteAllowed,
    isNB, isGPT, isKlein, nbAvailable, gptAvailable, klAvailable,
    nbProviderReady, gptProviderReady, nanoBananaProviderLabel,
    approveRemoteGeneration, currentAvailable, gptViaSub, gptPlanLabel, kleinHint,
  }
}
