import assert from 'node:assert/strict'
import test from 'node:test'

import { buildSettingsPatch } from './settingsPatch.js'
import { shouldBlockHashNavigation } from '../hooks/useUnsavedChangesGuard.js'

test('settings patch contains only fields changed by this draft', () => {
  const loaded = {
    server: { host: '127.0.0.1', port: 5050 },
    captioning: { backend: 'auto' },
  }
  const draft = {
    server: { host: '127.0.0.1', port: 5050 },
    captioning: { backend: 'ollama' },
  }
  assert.deepEqual(buildSettingsPatch(loaded, draft), {
    captioning: { backend: 'ollama' },
  })
})

test('settings patch treats arrays atomically and omits unchanged values', () => {
  assert.deepEqual(buildSettingsPatch(
    { engines: { enabled: ['klein'], default: 'klein' } },
    { engines: { enabled: ['klein', 'chatgpt'], default: 'klein' } },
  ), { engines: { enabled: ['klein', 'chatgpt'] } })
  assert.equal(buildSettingsPatch({ server: { port: 5050 } }, { server: { port: 5050 } }), undefined)
})

test('navigation guard allows settings sections but blocks routes that discard the draft', () => {
  assert.equal(shouldBlockHashNavigation('#/settings/server', '#/settings/engines', 'settings'), false)
  assert.equal(shouldBlockHashNavigation('#/settings/server', '#/datasets', 'settings'), true)
  assert.equal(shouldBlockHashNavigation('#/setup', '#/datasets', 'setup'), true)
})
