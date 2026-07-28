import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8')

test('capability refresh publishes only the newest response and exposes initial failure', () => {
  const context = read('context/CapabilitiesContext.jsx')
  const app = read('App.jsx')
  assert.match(context, /const request = \+\+requestRef\.current/)
  assert.match(context, /request !== requestRef\.current/)
  assert.match(context, /value=\{\{ caps, loading, error, refresh \}\}/)
  assert.match(app, /if \(loading \|\| error \|\| caps\.configured\) return/)
})

test('settings failures are recoverable and late saves preserve newer drafts', () => {
  const settings = read('pages/SettingsPage.jsx')
  assert.match(settings, /Couldn’t load settings/)
  assert.match(settings, />\s*Retry\s*</)
  assert.match(settings, /reconcileServerSnapshot\(current, submittedConfig, data\.config\)/)
  assert.match(settings, /value !== submittedSecrets\[key\]/)
})

test('settings and guide navigation use canonical links and focus routed headings', () => {
  const settings = read('pages/SettingsPage.jsx')
  const guide = read('pages/GuidePage.jsx')
  const primitives = read('components/settings/primitives.jsx')
  assert.match(settings, /<Link key=\{s\.id\} to=\{`\/settings\/\$\{s\.id\}`\}/)
  assert.match(guide, /<Link key=\{c\.id\} to=\{`\/guide\/\$\{c\.id\}`\}/)
  assert.match(settings, /<Navigate to="\/settings\/overview" replace \/>/)
  assert.match(guide, /<Navigate to="\/guide\/getting-started" replace \/>/)
  assert.match(settings, /headingRef\.current\?\.focus\(\)/)
  assert.match(guide, /headingRef\.current\?\.focus\(\)/)
  assert.match(primitives, /<h1 ref=\{headingRef\} tabIndex=\{-1\}/)
})

test('settings edits invalidate stale connection results and count real search matches', () => {
  const settings = read('pages/SettingsPage.jsx')
  assert.match(settings, /const setField = [\s\S]*?setTestResults\(\{\}\)/)
  assert.match(settings, /const editSecretInputs = [\s\S]*?setTestResults\(\{\}\)/)
  assert.match(settings, /const matchingSections = SETTINGS_SECTIONS\.filter/)
  assert.match(settings, /\{matchingSections\.length\} section/)
})

test('settings enforce face and engine invariants', () => {
  const settings = read('pages/SettingsPage.jsx')
  const captioning = read('components/settings/CaptioningSection.jsx')
  const engines = read('components/settings/EnginesSection.jsx')
  assert.match(settings, /At least one image engine must remain enabled/)
  assert.match(settings, /next\.includes\(prev\.engines\.default\)/)
  assert.match(captioning, /orange < config\.face_scoring\.green/)
  assert.match(captioning, /aria-invalid=\{!thresholdsValid\}/)
  assert.match(engines, /disabled=\{!\(config\.engines\.enabled \|\| \[\]\)\.includes\(o\.id\)\}/)
})

test('setup labels secrets and cannot advance without a successful save and probe', () => {
  const setup = read('pages/SetupPage.jsx')
  const tool = read('components/setup/SetupToolBody.jsx')
  assert.match(tool, /aria-label=\{f\.label\}/)
  assert.match(setup, /const fresh = await persist\(\)/)
  assert.match(setup, /if \(!fresh\)/)
})

test('queued confirmations insert an activation boundary', () => {
  const dialog = read('components/common/ConfirmDialog.jsx')
  assert.match(dialog, /activationPendingRef\.current = true/)
  assert.match(dialog, /setTimeout\(\(\) =>[\s\S]*}, 300\)/)
  assert.match(dialog, /activeRef\.current \|\| activationPendingRef\.current/)
})

test('shell owns the only main landmark and sliders have accessible names', () => {
  const app = read('App.jsx')
  const routeSources = [
    read('pages/GuidePage.jsx'),
    read('components/dataset/studio/ComparisonStudio.jsx'),
    read('components/dataset/studio/LegacyDatasetStudio.jsx'),
  ].join('\n')
  assert.equal((app.match(/<main\b/g) || []).length, 1)
  assert.doesNotMatch(routeSources, /<main\b/)
  assert.match(read('components/shared/LockableSlider.jsx'), /aria-label=\{label\}/)
})

test('update polling has one nav owner and restart attempts are bounded', () => {
  const app = read('App.jsx')
  const readiness = read('utils/restartReadiness.js')
  assert.equal((app.match(/<CheckUpdatesButton \/>/g) || []).length, 1)
  assert.match(readiness, /deadlineMs = 120_000/)
  assert.match(readiness, /health\.restart_nonce === restartNonce/)
  assert.match(readiness, /probeImage\(probe\.toString\(\)\)/)
  assert.match(app, /did not become reachable within two minutes/)
})
