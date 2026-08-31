import assert from 'node:assert/strict'
import test from 'node:test'
import {
  deriveCapabilitySummary, deriveSessionStatus, deriveSetupGroups, deriveSetupSteps, SETUP_STEP_IDS,
} from './useSetupSteps.js'

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

test('setup completion is independent from whether local services are currently running', () => {
  const steps = deriveSetupSteps({
    comfyui: {
      reachable: false,
      api_url: 'http://127.0.0.1:8188',
      dir_configured: true,
      dir_valid: true,
      models: { klein: ['flux-2-klein-9b-fp8.safetensors'] },
    },
    local_vision: {
      provider: 'lmstudio', label: 'LM Studio', reachable: false, model_ready: false,
      url: 'http://127.0.0.1:1234/v1', vision_model: 'google/gemma-4-12b-qat',
    },
    aitoolkit: { configured: true, valid: false },
  })

  assert.equal(steps.find((step) => step.id === 'comfyui').setupComplete, true)
  assert.equal(steps.find((step) => step.id === 'comfyui').runtimeReady, false)
  assert.equal(steps.find((step) => step.id === 'ollama').setupComplete, true)
  assert.equal(steps.find((step) => step.id === 'ollama').runtimeReady, false)
  assert.equal(steps.find((step) => step.id === 'training').setupComplete, true)
  assert.equal(steps.find((step) => step.id === 'training').runtimeReady, false)
})

test('ComfyUI session instructions retain the detected macOS application launcher', () => {
  const step = deriveSetupSteps({
    comfyui: {
      folder_launcher: {
        cwd: '/Users/test/ComfyUI',
        command: './.venv/bin/python main.py --listen 127.0.0.1 --port 8188',
        managed_by_desktop: true,
      },
      app: {
        name: 'Comfy Desktop',
        path: '/Applications/Comfy Desktop.app',
        launch_command: 'open -b com.todesktop.241012ess7yxs0e',
      },
    },
  }).find((item) => item.id === 'comfyui')

  assert.equal(step.app.name, 'Comfy Desktop')
  assert.equal(step.app.launchCommand, 'open -b com.todesktop.241012ess7yxs0e')
  assert.equal(step.folderLauncher.cwd, '/Users/test/ComfyUI')
  assert.equal(step.folderLauncher.command,
    './.venv/bin/python main.py --listen 127.0.0.1 --port 8188')
  assert.equal(step.folderLauncher.managedByDesktop, true)
})

test('ComfyUI labels distinguish Desktop from Git installations', () => {
  const desktop = deriveSetupSteps({ comfyui: { install_type: 'desktop' } })
    .find((step) => step.id === 'comfyui')
  const git = deriveSetupSteps({ comfyui: { install_type: 'git' } })
    .find((step) => step.id === 'comfyui')

  assert.equal(desktop.installLabel, 'ComfyUI Desktop')
  assert.match(desktop.title, /^ComfyUI Desktop —/)
  assert.equal(git.installLabel, 'ComfyUI from Git / code')
  assert.match(git.title, /^ComfyUI from Git \/ code —/)
  assert.equal(deriveSessionStatus([desktop])[0].label, 'ComfyUI Desktop')
  assert.equal(deriveSessionStatus([git])[0].label, 'ComfyUI from Git / code')
})

test('session status reports the same five tool groups instead of ten unexplained capabilities', () => {
  const rows = deriveSessionStatus(deriveSetupSteps({
    engines: { chatgpt: true },
    comfyui: { reachable: false, dir_valid: true, models: { klein: ['klein.safetensors'] } },
    local_vision: {
      provider: 'lmstudio', label: 'LM Studio', reachable: true, model_ready: true,
      url: 'http://127.0.0.1:1234/v1', vision_model: 'vision-model',
    },
    face_scoring: true, masks: true, watermark_inpaint: true,
    aitoolkit: { configured: true, valid: false },
  }))

  assert.equal(rows.length, 5)
  assert.deepEqual(rows.map((row) => row.id), SETUP_STEP_IDS)
  assert.equal(rows.find((row) => row.id === 'comfyui').status, 'not running')
  assert.equal(rows.find((row) => row.id === 'ollama').status, 'running')
  assert.equal(rows.find((row) => row.id === 'training').status, 'environment missing')
})

test('setup groups express core choices separately from optional enhancements', () => {
  const steps = deriveSetupSteps({
    engines: { nanobanana: false, chatgpt: false, klein: true },
    comfyui: { reachable: true, dir_valid: true, models: { klein: ['klein.safetensors'] } },
    local_vision: {
      provider: 'lmstudio', label: 'LM Studio', reachable: false, model_ready: false,
      url: 'http://127.0.0.1:1234/v1', vision_model: 'vision-model',
    },
  })
  const groups = deriveSetupGroups(steps)

  assert.deepEqual(groups.map((group) => group.id), ['generation', 'automation', 'extras'])
  assert.equal(groups.find((group) => group.id === 'generation').requirement, 'Choose at least one provider')
  assert.equal(groups.find((group) => group.id === 'generation').complete, true)
  assert.equal(groups.find((group) => group.id === 'automation').required, true)
  assert.equal(groups.find((group) => group.id === 'automation').complete, true)
  assert.equal(groups.find((group) => group.id === 'extras').required, false)
  assert.equal(steps.find((step) => step.id === 'image').providerConfigured, false)
})
