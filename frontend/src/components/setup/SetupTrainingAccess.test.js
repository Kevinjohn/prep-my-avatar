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
