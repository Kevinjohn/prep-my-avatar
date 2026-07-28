import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8')

test('deferred local training snapshots the explicit fresh or resume choice', () => {
  const source = read('hooks/useTrainingLaunch.js')
  const enqueue = source.slice(source.indexOf('const enqueue = async'), source.indexOf('const dequeue = async'))
  const schedule = source.slice(source.indexOf('const schedule = async'), source.indexOf('// Launch-time GPU'))
  for (const action of [enqueue, schedule]) {
    assert.match(action, /await askResumeOrFresh\(\)/)
    assert.match(action, /trainingLaunchBody\([\s\S]*mode/)
  }
  assert.match(read('components/dataset/trainingLaunchPolicy.js'), /fresh: config\.mode === 'fresh'/)
})

test('stopping local training discloses and preserves or explicitly clears deferred jobs', () => {
  const panel = read('components/dataset/TrainingPanel.jsx')
  const hook = read('hooks/useDataset.js')
  assert.match(panel, /Stop and keep queue/)
  assert.match(panel, /Stop \+ cancel queue/)
  assert.match(panel, /clearQueue: false/)
  assert.match(panel, /clearQueue: true/)
  assert.match(hook, /clear_queue: clearQueue/)
})

test('crop confirmation is synchronous single-flight and locks modal actions', () => {
  const source = read('components/dataset/CropModal.jsx')
  assert.match(source, /if \(!box \|\| submittingRef\.current\) return/)
  assert.match(source, /submittingRef\.current = true/)
  assert.match(source, /disabled=\{!box \|\| submitting\}/)
  assert.equal((source.match(/disabled=\{submitting\}/g) || []).length, 2)
})

test('Studio resume and billing warnings use explicit global scopes', () => {
  const studio = read('hooks/useLoraTestStudio.js')
  const panel = read('components/dataset/TrainingPanel.jsx')
  const runs = read('pages/CloudRunsPage.jsx')
  assert.match(studio, /if \(!family\)/)
  assert.match(studio, /lora-test\/resume`, \{ family \}/)
  assert.match(panel, /cloudStatus\.recovery_required/)
  assert.match(runs, /data\?\.recovery_required/)
  assert.doesNotMatch(runs, /recent\.some\(\(r\) => r\.status === 'error_pod_kept'\)/)
})

test('cloud operational guardrails clamp both sides of every displayed bound', () => {
  const source = read('components/settings/TrainingSection.jsx')
  assert.match(source, /Math\.min\(10, Math\.max\(1,/)
  assert.match(source, /Math\.min\(5, Math\.max\(0\.1,/)
  assert.match(source, /monthly_budget_usd', Math\.max\(0,/)
  assert.match(source, /Math\.min\(240, Math\.max\(5,/)
})
