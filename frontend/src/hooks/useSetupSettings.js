import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { apiFetch, putJson } from '../api/fetchClient'
import { buildSettingsPatch } from '../utils/settingsPatch'
import { reconcileServerSnapshot } from '../utils/serverSnapshot'
import { useUnsavedChangesGuard } from './useUnsavedChangesGuard'

/** Owns Setup's load, draft, conflict-safe persistence, and detection lifecycle. */
export function useSetupSettings({ refresh, toast }) {
  const [config, setConfig] = useState(null)
  const [secretsPresence, setSecretsPresence] = useState({})
  const [secretInputs, setSecretInputs] = useState({})
  const [busy, setBusy] = useState(false)
  const [loadError, setLoadError] = useState(false)
  const [detected, setDetected] = useState(null)
  const [detecting, setDetecting] = useState(false)
  const [scanned, setScanned] = useState(false)
  const [scanError, setScanError] = useState(null)
  const savedConfigRef = useRef(null)
  const configRef = useRef(config)
  const secretInputsRef = useRef(secretInputs)
  const autodetectedRef = useRef(false)
  useEffect(() => { configRef.current = config }, [config])
  useEffect(() => { secretInputsRef.current = secretInputs }, [secretInputs])
  const dirty = useMemo(() => savedConfigRef.current != null
    && (JSON.stringify(config) !== JSON.stringify(savedConfigRef.current)
      || Object.values(secretInputs).some((value) => (value || '').trim())), [config, secretInputs])
  useUnsavedChangesGuard(dirty, 'setup')

  const load = useCallback(async () => {
    try {
      const data = await apiFetch('/api/settings')
      setConfig(data.config); setSecretsPresence(data.secrets); setLoadError(false)
      savedConfigRef.current = data.config
    } catch (error) {
      setLoadError(true); toast.error(`Failed to load settings: ${error.message}`)
    }
  }, [toast])
  useEffect(() => { load() }, [load])

  const runAutodetect = useCallback(async (baseConfig) => {
    setDetecting(true); setScanError(null)
    try {
      const result = await apiFetch('/api/setup/autodetect')
      setDetected(result)
      // Detection is an automatic scoped write, not a save of the visible
      // draft. Build exclusively from the last server snapshot so edits made
      // while the scan is running can never leak into this PUT.
      const baseline = structuredClone(savedConfigRef.current || baseConfig)
      const next = structuredClone(baseline)
      let changed = false
      const fill = (section, key, value) => {
        if (value && !next?.[section]?.[key]) {
          next[section] = { ...(next[section] || {}), [key]: value }; changed = true
        }
      }
      fill('ollama', 'url', result.ollama?.url)
      fill('ollama', 'vision_model', result.ollama?.vision_model)
      fill('comfyui', 'api_url', result.comfyui?.api_url)
      fill('comfyui', 'base_dir', result.comfyui?.base_dir)
      if (changed) {
        const saved = await putJson('/api/settings', {
          config: buildSettingsPatch(baseline, next) || {},
        })
        // Three-way merge against the snapshot submitted by autodetect: apply
        // detected/server-canonical fields only where the user has not edited
        // since that snapshot, and preserve every intervening draft value.
        setConfig((current) => reconcileServerSnapshot(current, baseline, saved.config))
        savedConfigRef.current = saved.config
      }
      await refresh(true)
      return result
    } catch (error) {
      setScanError(error.message || 'The machine scan could not be completed.')
      return null
    } finally { setDetecting(false); setScanned(true) }
  }, [refresh])
  useEffect(() => {
    if (config && !autodetectedRef.current) {
      autodetectedRef.current = true; runAutodetect(config)
    }
  }, [config, runAutodetect])

  const setField = (section, key, value) => setConfig((previous) => ({
    ...previous, [section]: { ...previous[section], [key]: value },
  }))
  const applyDetectedPath = async (section, key, value) => {
    const next = { ...config, [section]: { ...config[section], [key]: value } }
    try {
      const saved = await putJson('/api/settings', {
        config: buildSettingsPatch(savedConfigRef.current, next) || {},
      })
      setConfig((current) => reconcileServerSnapshot(current, next, saved.config))
      savedConfigRef.current = saved.config
      await refresh(true); toast.success('Applied.')
    } catch (error) { toast.error(`Save failed: ${error.message}`) }
  }
  const persist = async () => {
    const submittedConfig = configRef.current
    const submittedSecrets = secretInputsRef.current
    setBusy(true)
    try {
      const secrets = Object.fromEntries(Object.entries(submittedSecrets)
        .map(([key, value]) => [key, (value || '').trim()]).filter(([, value]) => value))
      const data = await putJson('/api/settings', {
        config: buildSettingsPatch(savedConfigRef.current, submittedConfig) || {}, secrets,
      })
      setConfig((current) => reconcileServerSnapshot(current, submittedConfig, data.config))
      setSecretsPresence(data.secrets)
      setSecretInputs((current) => Object.fromEntries(Object.entries(current)
        .filter(([key, value]) => value !== submittedSecrets[key])))
      savedConfigRef.current = data.config
      const fresh = await refresh(true); toast.success('Saved.'); return fresh
    } catch (error) { toast.error(`Save failed: ${error.message}`); return null }
    finally { setBusy(false) }
  }
  return { config, setConfig, secretsPresence, setSecretsPresence, secretInputs,
    setSecretInputs, busy, loadError, detected, detecting, scanned, scanError,
    dirty, load, runAutodetect, setField, persist, applyDetectedPath }
}
