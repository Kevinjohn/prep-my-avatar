/**
 * Capability probes — what's actually configured/reachable right now
 * (GET /api/capabilities). Drives feature gating (e.g. the Studio nav item)
 * and the onboarding redirect when the app has never been configured.
 */
import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react'
import { apiFetch } from '../api/fetchClient'

const CapabilitiesContext = createContext(null)

const EMPTY_CAPS = {
  configured: false,
  engines: { nanobanana: false, chatgpt: false, klein: false },
  comfyui: { reachable: false, api_url: '', models: {} },
  ollama: { reachable: false, installed: false, binary_path: '', url: '', vision_model: '', vision_model_ready: false },
  aitoolkit: { configured: false, valid: false },
  captioners: { joycaption: false, ollama: false },
  face_scoring: false,
  masks: false,
  watermark_inpaint: false,
  training_visible: false,
  cloud_training: false,
  studio_visible: false,
  generation_pricing: {
    version: 1, as_of: null, currency: 'USD',
    per_image: { nanobanana: 0, chatgpt_api: 0 },
  },
  resolution_metadata: null,
}

export function CapabilitiesProvider({ children }) {
  const [caps, setCaps] = useState(EMPTY_CAPS)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const requestRef = useRef(0)
  useEffect(() => () => { requestRef.current += 1 }, [])

  const refresh = useCallback(async (force = false) => {
    const request = ++requestRef.current
    setLoading(true)
    try {
      const data = await apiFetch(`/api/capabilities${force ? '?force=1' : ''}`)
      if (request !== requestRef.current) return null
      setCaps(data)
      setError(null)
      return data
    } catch (cause) {
      // Keep the last-known caps on a transient network error rather than
      // resetting to EMPTY_CAPS — that would bounce the user into onboarding.
      if (request === requestRef.current) setError(cause)
      return null
    } finally {
      if (request === requestRef.current) setLoading(false)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  return (
    <CapabilitiesContext.Provider value={{ caps, loading, error, refresh }}>
      {children}
    </CapabilitiesContext.Provider>
  )
}

export function useCapabilities() {
  const ctx = useContext(CapabilitiesContext)
  if (!ctx) throw new Error('useCapabilities must be used within CapabilitiesProvider')
  return ctx
}
