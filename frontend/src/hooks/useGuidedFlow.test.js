import test from 'node:test';
import assert from 'node:assert/strict';
import { deriveSteps } from './useGuidedFlow.js';

const CAPS = {
  ollama: { reachable: true, vision_model_ready: true },
  training_visible: false,
  studio_visible: false,
};

function dataset(overrides = {}) {
  return {
    images: [{ id: 1, source: 'import', filename: 'real.webp', status: 'keep', caption: '' }],
    coverage_plan: {
      available: true,
      summary: { unclassified: 0, gaps: 2 },
      recommended_variation_ids: ['face_front_neutral'],
    },
    anchor_plan: { selected_total: 1, limit: 14 },
    ...overrides,
  };
}

test('vision-ready imported corpora stop at coverage review when metadata is unknown', () => {
  const d = dataset({
    coverage_plan: { available: true, summary: { unclassified: 1, gaps: 3 },
      recommended_variation_ids: ['face_front_neutral'] },
  });
  assert.equal(deriveSteps(d, CAPS).nextStep.id, 'review');
});

test('targeted gap generation remains an optional fallback for a mapped corpus', () => {
  const result = deriveSteps(dataset(), CAPS);
  assert.equal(result.steps.find((step) => step.id === 'generate').optional, true);
  assert.equal(result.nextStep.id, 'caption');
});

test('generated candidates must be curated before they count as completed work', () => {
  const d = dataset({ images: [
    { id: 1, source: 'import', filename: 'real.webp', status: 'keep', caption: '' },
    { id: 2, source: 'generated', filename: 'candidate.webp', status: 'pending', caption: '' },
  ] });
  assert.equal(deriveSteps(d, CAPS).nextStep.id, 'curate');
});
