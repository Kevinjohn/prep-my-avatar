import assert from 'node:assert/strict'
import test from 'node:test'
import { localVisionGateReason, ollamaGateReason, setupNavigation } from './setupWorkflow.js'

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
