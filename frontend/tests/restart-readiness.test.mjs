import assert from 'node:assert/strict'
import test from 'node:test'
import { restartTarget, waitForRestart } from '../src/utils/restartReadiness.js'

test('same-port restart accepts the matching replacement nonce without an outage', async () => {
  globalThis.window = { location: { origin: 'http://127.0.0.1:5050' } }
  let calls = 0
  const ready = await waitForRestart({
    restartNonce: 'replacement-1',
    target: new URL('http://127.0.0.1:5050/#/settings'),
    pause: async () => {},
    deadlineMs: 1000,
    fetchReady: async () => {
      calls += 1
      return new Response(JSON.stringify({
        ok: true,
        restart_acknowledged: true,
        restart_nonce: 'replacement-1',
      }), {
        status: 200, headers: { 'content-type': 'application/json' },
      })
    },
  })
  assert.equal(ready, true)
  assert.equal(calls, 1, 'a healthy replacement does not require a failed poll first')
})

test('port-changing restart uses the nonce image probe instead of cross-origin fetch', async () => {
  globalThis.window = { location: { origin: 'http://127.0.0.1:5050' } }
  let probed
  const ready = await waitForRestart({
    restartNonce: 'replacement-2',
    target: new URL('http://127.0.0.1:6060/#/settings'),
    pause: async () => {}, deadlineMs: 1000,
    fetchReady: async () => { throw new Error('cross-origin fetch must not run') },
    probeImage: async (url) => { probed = url; return true },
  })
  assert.equal(ready, true)
  assert.match(probed, /^http:\/\/127\.0\.0\.1:6060\/api\/health\/restart\/replacement-2\.gif/)
  assert.equal(restartTarget({ href: 'http://127.0.0.1:5050/#/settings' }, 6060).port, '6060')
})
