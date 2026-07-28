import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8')

test('training launch is gated by persisted config and authoritative preflight', () => {
  const source = read('components/dataset/TrainingPanel.jsx')
  const launch = read('hooks/useTrainingLaunch.js')
  assert.match(source, /baseInfoState === 'ready' && preflightState === 'ready'/)
  assert.match(source, /preflightSummary\.floor/)
  assert.doesNotMatch(source, /const TRAIN_MIN/)
  assert.match(launch, /Training readiness could not be checked/)
})

test('checkpoint failures stop launch and preserve the last successful inventory', () => {
  const launch = read('hooks/useTrainingLaunch.js')
  const browser = read('components/dataset/useCheckpointBrowser.js')
  const hook = read('hooks/useDataset.js')
  assert.match(launch, /Checkpoints could not be checked\. Training was not started/)
  assert.match(browser, /Showing the last successful list/)
  assert.doesNotMatch(hook, /catch \{ return \{ checkpoints: \[\], imported: \[\] \}; \}/)
})

test('running progress and checkpoint continuation retain their immutable family', () => {
  const panel = read('components/dataset/TrainingPanel.jsx')
  const view = read('components/dataset/TrainingCheckpointBrowserView.jsx')
  const hook = read('hooks/useDataset.js')
  assert.match(panel, /status\.current\.train_type \?\? trainType/)
  assert.match(view, /continueTraining\(1000, checkpointBase, variant, checkpointTrainType\)/)
  assert.match(hook, /body\.train_type = trainType/)
})

test('crop exposes labeled keyboard-editable geometry', () => {
  const source = read('components/dataset/CropModal.jsx')
  assert.match(source, /Crop selection coordinates and size/)
  for (const label of ['Left', 'Top', 'Width', 'Height']) assert.match(source, new RegExp(`'${label}'`))
  assert.match(source, /setBoxField/)
})

test('Studio sends the complete canonical winning generation config', () => {
  const source = read('hooks/useLoraTestStudio.js')
  assert.match(source, /generation_config: Object\.fromEntries/)
  for (const field of ['extra_loras', 'krea_rebalance', 'negative', 'sampler', 'scheduler',
    'weight_dtype', 'enhancer_strength', 'detail_amount', 'resolution_tier', 'init_image', 'denoise']) {
    assert.match(source, new RegExp(field))
  }
})

test('runs hub rejects stale refreshes and exposes initial refresh failures', () => {
  const source = read('pages/CloudRunsPage.jsx')
  assert.match(source, /const pollRequest = useRef\(0\)/)
  assert.match(source, /requestId !== pollRequest\.current/)
  assert.match(source, /role="alert"/)
  assert.match(source, /Retry now/)
  assert.match(source, /selected\.filter\(\(key\) => visible\.has\(key\)\)/)
})

test('runs hub renders robust timestamps, statuses, cleanup errors, and integer steps', () => {
  const source = read('pages/CloudRunsPage.jsx')
  assert.match(source, /\[\+-\]\\d\{2\}:\?\\d\{2\}/)
  assert.match(source, /run\.status \|\| \(run\.source === 'local' \? 'recorded' : 'unknown'\)/)
  assert.match(source, /Cloud cleanup failed/)
  assert.match(source, /Number\.isSafeInteger\(extra\)/)
  assert.doesNotMatch(source, /const extra = parseInt/)
})

test('training panel reports all checkpoints and preserves failed actions', () => {
  const source = read('components/dataset/TrainingPanel.jsx')
  const browser = read('components/dataset/trainingPanelResponsibilities.js')
  const view = read('components/dataset/TrainingCheckpointBrowserView.jsx')
  const presets = read('components/dataset/useTrainingPresets.js')
  assert.match(browser, /cloudCheckpoints\.length/)
  assert.match(view, /cloudCkpts\.length} synced cloud/)
  assert.match(presets, /if \(!result\.ok\) return reportError\(result, 'Preset deletion failed'\)/)
  assert.match(source, /const openTrainingFolder = async/)
  assert.match(source, /Could not open the folder/)
})

test('queued training displays its immutable recipe and step input is exact', () => {
  const source = read('components/dataset/TrainingPanel.jsx')
  const policy = read('components/dataset/trainingLaunchPolicy.js')
  const launch = read('hooks/useTrainingLaunch.js')
  assert.match(launch, /const queuedItem = .*\.find/)
  assert.match(source, /trainFamilyLabel\(queuedItem\.train_type\)/)
  assert.match(source, /trainFamilyLabel\(q\.train_type\)/)
  assert.match(launch, /parseTrainingSteps\(stepsOverride\)/)
  assert.match(policy, /Number\.isSafeInteger\(parsed\)/)
  assert.match(source, /hasInvalidStepsOverride/)
  assert.doesNotMatch(launch, /parseInt\(stepsOverride/)
})

test('custom-weight confirmation does not also produce an error toast', () => {
  const hook = read('hooks/useDataset.js')
  assert.match(hook, /!String\(d\.error \|\| ''\)\.includes\('CUSTOM_WEIGHTS_UNVERIFIED'\)/)
})
