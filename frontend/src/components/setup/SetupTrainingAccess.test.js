import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync(new URL('./SetupToolBody.jsx', import.meta.url), 'utf8');

test('LoRA setup includes gated-family access and the full dependency map', () => {
  assert.match(source, /Hugging Face access for gated training families/);
  assert.match(source, /secretsPresence\.HF_TOKEN/);
  assert.match(source, /aria-label="Hugging Face token"/);
  assert.match(source, /saveSecretThenTest\('HF_TOKEN', null\)/);
  assert.match(source, /TrainingRequirementsPanel/);
});

test('setup offers both cloud GPU providers as the alternative to a local GPU', () => {
  assert.match(source, /No GPU\? You can skip this step: add a <strong>cloud GPU API key \(vast\.ai or RunPod\)<\/strong> in\s+Settings instead and train in the cloud/);
});
