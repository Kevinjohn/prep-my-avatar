import { useCallback, useEffect, useState } from 'react'
import { getJson } from '../api/fetchClient'

const EMPTY_STATUS = { in_progress: false, installed: true, queue: [], current: null }
const EMPTY_CLOUD = { configured: false, limit: 1, actives: [], active: null, total_price_per_hour: 0, last: null }

export function useTrainingMonitoring({ trainingVisible, cloudTraining, onNavigationStateChange }) {
  const [status, setStatus] = useState(EMPTY_STATUS)
  const [statusLoaded, setStatusLoaded] = useState(false)
  const [cloudStatus, setCloudStatus] = useState(EMPTY_CLOUD)
  const refreshStatus = useCallback(async () => {
    try {
      const data = await getJson('/api/dataset/train/status')
      setStatus(data?.available === false
        ? { in_progress: false, installed: false, queue: [], current: null } : data)
      setStatusLoaded(true)
      return data
    } catch { return null }
  }, [])
  useEffect(() => {
    setStatusLoaded(false)
    if (!trainingVisible) return undefined
    refreshStatus()
    const timer = setInterval(refreshStatus, 10000)
    return () => clearInterval(timer)
  }, [trainingVisible, refreshStatus])
  useEffect(() => {
    onNavigationStateChange?.({
      ready: !trainingVisible || statusLoaded,
      queueCount: Array.isArray(status.queue) ? status.queue.length : 0,
    })
  }, [trainingVisible, statusLoaded, status.queue, onNavigationStateChange])
  useEffect(() => {
    if (!cloudTraining) return undefined
    let alive = true; let timer
    const tick = async () => {
      try { const data = await getJson('/api/dataset/train/cloud/status'); if (alive) setCloudStatus(data) } catch { /* transient */ }
      if (alive) timer = setTimeout(tick, 5000)
    }
    timer = setTimeout(tick, 0)
    return () => { alive = false; clearTimeout(timer) }
  }, [cloudTraining])
  return { status, statusLoaded, cloudStatus, refreshStatus }
}
