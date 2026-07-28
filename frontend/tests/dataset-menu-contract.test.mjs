import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

test('setup never suggests the slow Qwen thinking tag for captioning', () => {
  const setup = readFileSync(new URL('../src/components/setup/SetupToolBody.jsx', import.meta.url), 'utf8')
  const tools = readFileSync(new URL('../src/components/settings/LocalToolsSection.jsx', import.meta.url), 'utf8')
  assert.match(setup, /huihui_ai\/qwen3-vl-abliterated:8b-instruct/)
  assert.doesNotMatch(setup, /huihui_ai\/qwen3-vl-abliterated:8b['"]/)
  assert.match(tools, /huihui_ai\/qwen3-vl-abliterated:8b-instruct/)
})
