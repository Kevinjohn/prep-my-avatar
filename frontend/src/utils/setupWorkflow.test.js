import assert from 'node:assert/strict'
import test from 'node:test'
import {
  detailBackScreen, localVisionGateReason, ollamaGateReason, setupNavigation,
} from './setupWorkflow.js'

test('tool details return to the checklist that opened them', () => {
  assert.equal(detailBackScreen('session', 6), 6)
  assert.equal(detailBackScreen('setup', 6), 0)
  assert.equal(detailBackScreen(null, 6), 0)
})

test('setup navigation skips ready steps in both directions', () => {
  const model = setupNavigation(['a', 'b', 'c'], {
    a: { status: 'ready' }, b: { status: 'partial' }, c: { status: 'ready' },
  }, 2)
  assert.equal(model.kind, 'b')
  assert.equal(model.firstUnfinished, 'b')
  assert.equal(model.nextUnfinished(0), 'b')
  assert.equal(model.previousUnfinished(2), 'b')
  assert.equal(model.allReady, false)
})

test('setup navigation treats completed configuration as finished even when runtime is stopped', () => {
  const model = setupNavigation(['comfyui', 'vision', 'training'], {
    comfyui: { status: 'available', setupComplete: true },
    vision: { status: 'available', setupComplete: true },
    training: { status: 'available', setupComplete: true },
  }, 0)

  assert.equal(model.firstUnfinished, null)
  assert.equal(model.allReady, true)
})

test('local vision gate names the selected OpenAI-compatible server', () => {
  assert.match(localVisionGateReason({
    status: 'partial', provider: 'lmstudio', providerLabel: 'LM Studio', reachable: false,
  }), /LM Studio is not reachable/)
  assert.match(localVisionGateReason({
    status: 'partial', provider: 'llamacpp', providerLabel: 'llama.cpp', reachable: true,
    visionModelReady: false,
  }), /Load the configured vision model in llama\.cpp/)
})

test('Ollama gate distinguishes absent, stopped, and missing model states', () => {
  assert.match(ollamaGateReason({ status: 'partial', installed: false, reachable: false }), /isn't installed/)
  assert.match(ollamaGateReason({ status: 'partial', installed: true, reachable: false }), /not running/)
  assert.match(ollamaGateReason({ status: 'partial', reachable: true, visionModelReady: false }), /vision model/)
  assert.equal(ollamaGateReason({ status: 'ready' }), null)
})
