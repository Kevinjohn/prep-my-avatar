import test from 'node:test';
import assert from 'node:assert/strict';

import { isCleanAdmissionCandidate, needsQualityReview } from './corpusAdmission.js';

const clean = {
  id: 1,
  status: 'pending',
  training_usefulness: 'green',
  analysis: { face: { quality: 'green' } },
  face_state: 'scorable',
  face_score: 0.65,
};

test('clean admission requires verified identity as well as clean pixels', () => {
  assert.equal(isCleanAdmissionCandidate(clean, 0.50), true);
  assert.equal(isCleanAdmissionCandidate({ ...clean, face_score: 0.30 }, 0.50), false);
  assert.equal(isCleanAdmissionCandidate({ ...clean, face_state: 'no_face', face_score: null }), false);
  assert.equal(isCleanAdmissionCandidate({ ...clean, analysis: {} }), false);
});

test('known watermarks and duplicates never enter clean bulk admission', () => {
  assert.equal(isCleanAdmissionCandidate({ ...clean, watermark_state: 'detected' }), false);
  assert.equal(isCleanAdmissionCandidate({ ...clean, duplicate_of_id: 9 }), false);
  assert.equal(isCleanAdmissionCandidate(clean, 0.50, new Set([clean.id])), false);
});

test('unchecked face-region QA remains visible in quality review', () => {
  assert.equal(needsQualityReview(clean), false);
  assert.equal(needsQualityReview({ ...clean, analysis: {} }), true);
  assert.equal(needsQualityReview({ ...clean, face_state: 'too_small', face_score: null }), true);
});
