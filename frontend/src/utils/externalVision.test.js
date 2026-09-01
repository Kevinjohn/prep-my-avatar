import test from 'node:test';
import assert from 'node:assert/strict';

import { externalVisionPayload, externalVisionWarning } from './externalVision.js';

test('local vision payload does not claim remote consent', () => {
  assert.deepEqual(externalVisionPayload('configured'), {});
});

test('remote vision payload carries explicit per-request acknowledgement', () => {
  assert.deepEqual(externalVisionPayload('openai'), {
    provider: 'openai',
    allow_external_images: true,
  });
});

test('ChatGPT subscription is a distinct acknowledged provider', () => {
  assert.deepEqual(externalVisionPayload('chatgpt'), {
    provider: 'chatgpt',
    allow_external_images: true,
  });
  assert.match(externalVisionWarning('chatgpt', 30).title, /ChatGPT subscription/);
});

test('remote warning names the destination and transmission', () => {
  const warning = externalVisionWarning('gemini', 30);
  assert.match(warning.title, /Google Gemini/);
  assert.match(warning.message, /30 dataset images will leave this machine/);
  assert.match(warning.message, /API/);
});
