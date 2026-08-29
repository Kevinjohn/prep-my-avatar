import assert from 'node:assert/strict'
import test from 'node:test'
import { deriveCapabilitySummary, deriveSetupSteps, SETUP_STEP_IDS } from './useSetupSteps.js'

test('setup derivation always exposes the five wizard steps in order', () => {
  const steps = deriveSetupSteps({})

  assert.deepEqual(steps.map((step) => step.id), SETUP_STEP_IDS)
  assert.equal(steps.length, 5)
  assert.match(steps[0].title, /Image generation/)
  assert.match(steps[2].title, /Ollama, LM Studio, or llama\.cpp/)
})

test('selected LM Studio readiness replaces legacy Ollama state', () => {
  const capabilities = {
    ollama: {
      reachable: true, installed: true, vision_model_ready: true,
      url: 'http://127.0.0.1:11434', vision_model: 'ollama-model',
    },
    local_vision: {
      provider: 'lmstudio', label: 'LM Studio', reachable: false, model_ready: false,
      url: 'http://127.0.0.1:1234/v1', vision_model: 'lm-vision',
    },
  }

  const step = deriveSetupSteps(capabilities).find((item) => item.id === 'ollama')

  assert.equal(step.provider, 'lmstudio')
  assert.equal(step.providerLabel, 'LM Studio')
  assert.equal(step.status, 'available')
  assert.equal(step.installed, false)
  assert.equal(step.url, 'http://127.0.0.1:1234/v1')
  assert.equal(step.visionModel, 'lm-vision')
})

test('capability summary uses selected local vision model readiness', () => {
  const summary = deriveCapabilitySummary({
    local_vision: { reachable: true, model_ready: true },
    captioners: { local_vision: true },
  })

  assert.equal(summary.find((item) => item.label === 'Auto-framing & head-crop').ok, true)
  assert.equal(summary.find((item) => item.label === 'Captioning').ok, true)
})
