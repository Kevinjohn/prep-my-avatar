import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const modal = readFileSync(new URL('./PreflightModal.jsx', import.meta.url), 'utf8');

test('preflight identifies every flagged pixel-QA image and supports full-size review', () => {
  assert.match(modal, /quality_images: qualityImages/);
  assert.match(modal, /Pixel QA review/);
  assert.match(modal, /redQualityImages\.length/);
  assert.match(modal, /amber or incomplete/);
  assert.match(modal, /orderedQualityImages\.map/);
  assert.match(modal, /technical quality:/);
  assert.match(modal, /face-region quality:/);
  assert.match(modal, /Inspect .* at full size/);
  assert.match(modal, /Full-size QA preview/);
  assert.match(modal, /Reject this photo/);
});
