import { fetchWithCsrfRetry } from '../api/fetchClient.js'

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

export function restartTarget(location, port) {
  const target = new URL(location.href)
  target.port = String(port)
  return target
}

export function imageRestartProbe(url, timeoutMs = 3000) {
  return new Promise((resolve) => {
    const image = new Image()
    const timeout = setTimeout(() => { image.src = ''; resolve(false) }, timeoutMs)
    image.onload = () => { clearTimeout(timeout); resolve(true) }
    image.onerror = () => { clearTimeout(timeout); resolve(false) }
    image.src = `${url}${url.includes('?') ? '&' : '?'}t=${Date.now()}`
  })
}

/** Wait for the exact replacement process, without requiring an observed outage. */
export async function waitForRestart({ restartNonce, target, signal = undefined,
  fetchReady = fetchWithCsrfRetry, probeImage = imageRestartProbe,
  pause = delay, deadlineMs = 120_000 }) {
  const sameOrigin = target.origin === window.location.origin
  const deadline = Date.now() + deadlineMs
  while (Date.now() < deadline && !signal?.aborted) {
    await pause(1000)
    try {
      if (sameOrigin) {
        const response = await fetchReady('/api/health/ready', {
          cache: 'no-store', signal,
        })
        if (!response.ok) continue
        const health = await response.json()
        if (health.restart_acknowledged === true
            && health.restart_nonce === restartNonce) return true
      } else {
        const probe = new URL(`/api/health/restart/${encodeURIComponent(restartNonce)}.gif`, target)
        if (await probeImage(probe.toString())) return true
      }
    } catch { /* replacement is not ready yet */ }
  }
  return false
}
