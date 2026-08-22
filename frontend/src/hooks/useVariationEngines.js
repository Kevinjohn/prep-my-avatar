import { useEffect, useState } from 'react'
import { apiFetch } from '../api/fetchClient'
import { usePersistedPreference } from './usePersistedPreference'

/** Own persisted generator selection and settings/capability reconciliation. */
export function useVariationEngines(caps) {
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
      setEnabledEngines(data.config?.engines?.enabled || [])
      setChatgptAuth(data.config?.engines?.chatgpt_auth || 'auto')
      setRemoteAllowed(!!data.config?.privacy?.allow_remote_generation)
      setSettingsLoaded(true); setSettingsError(false)
    }).catch(() => {
      if (!cancelled) { setSettingsLoaded(false); setSettingsError(true) }
    })
    return () => { cancelled = true }
  }, [])
  const isNB = generator === 'nanobanana'
  const isGPT = generator === 'chatgpt'
  const isKlein = !isNB && !isGPT
  const nbAvailable = remoteAllowed && enabledEngines.includes('nanobanana') && caps.engines.nanobanana
  const gptAvailable = remoteAllowed && enabledEngines.includes('chatgpt') && caps.engines.chatgpt
  const klAvailable = enabledEngines.includes('klein') && caps.engines.klein
  const currentAvailable = settingsLoaded && (isKlein ? klAvailable : isNB ? nbAvailable : gptAvailable)
  useEffect(() => {
    if (currentAvailable || !settingsLoaded) return
    const first = nbAvailable ? 'nanobanana' : gptAvailable ? 'chatgpt' : klAvailable ? 'klein' : null
    if (first && first !== generator) setGenerator(first)
  }, [currentAvailable, nbAvailable, gptAvailable, klAvailable, generator, setGenerator, settingsLoaded])
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
