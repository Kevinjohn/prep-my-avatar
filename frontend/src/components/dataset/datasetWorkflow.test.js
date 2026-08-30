import test from 'node:test';
import assert from 'node:assert/strict';
import {
  DATASET_WORKFLOW_STEPS,
  adjacentDatasetStep,
  applicableDatasetSteps,
  datasetWorkflowPath,
  legacyWorkspaceStep,
  resolveDatasetStep,
  resumeDatasetStep,
  workflowStepForTarget,
} from './datasetWorkflow.js';

const slugs = (kind = 'character') => applicableDatasetSteps({ kind }).map((step) => step.slug);

test('character workflow follows the first-run guide order one page at a time', () => {
  assert.deepEqual(slugs(), [
    'import', 'review', 'anchors', 'coverage', 'reference', 'generate', 'curate',
    'captions', 'score', 'export', 'train', 'checkpoints', 'studio', 'backup',
  ]);
  assert.equal(new Set(DATASET_WORKFLOW_STEPS.map((step) => step.slug)).size,
    DATASET_WORKFLOW_STEPS.length);
});

test('concept and style omit only character-specific steps', () => {
  const expected = ['import', 'review', 'curate', 'captions', 'export', 'train',
    'checkpoints', 'studio', 'backup'];
  assert.deepEqual(slugs('concept'), expected);
  assert.deepEqual(slugs('style'), expected);
});

test('optional and capability-dependent steps stay visible in the workflow', () => {
  const steps = applicableDatasetSteps({
    kind: 'character',
    capabilities: { face_scoring: false, training_visible: false, studio_visible: false },
  });
  for (const slug of ['reference', 'generate', 'score', 'train', 'checkpoints', 'studio']) {
    assert.equal(steps.find((step) => step.slug === slug)?.optional, true, slug);
  }
});

test('resume selects the first incomplete required applicable step', () => {
  const completed = { import: true, review: true, anchors: false, coverage: false };
  assert.equal(resumeDatasetStep({ kind: 'character', completed }).slug, 'anchors');
  assert.equal(resumeDatasetStep({ kind: 'concept', completed }).slug, 'curate');
});

test('route resolution preserves applicable slugs and normalizes invalid ones to resume', () => {
  const completed = { import: true, review: true, curate: false };
  assert.equal(resolveDatasetStep({ requestedSlug: 'captions', kind: 'concept', completed }).slug,
    'captions');
  assert.equal(resolveDatasetStep({ requestedSlug: 'anchors', kind: 'concept', completed }).slug,
    'curate');
  assert.equal(resolveDatasetStep({ requestedSlug: 'not-a-step', kind: 'character', completed }).slug,
    'anchors');
});

test('adjacent navigation skips inapplicable pages and stops at workflow ends', () => {
  assert.equal(adjacentDatasetStep('review', 1, { kind: 'concept' }).slug, 'curate');
  assert.equal(adjacentDatasetStep('curate', -1, { kind: 'concept' }).slug, 'review');
  assert.equal(adjacentDatasetStep('import', -1, { kind: 'concept' }), null);
  assert.equal(adjacentDatasetStep('backup', 1, { kind: 'character' }), null);
});

test('legacy section and panel links map to the closest canonical step', () => {
  const cases = [
    ['section=images', 'curate'],
    ['section=add&panel=import', 'import'],
    ['section=add&panel=corpus', 'review'],
    ['section=add&panel=coverage', 'coverage'],
    ['section=add&panel=reference', 'reference'],
    ['section=add&panel=generate', 'generate'],
    ['section=curation&panel=face-analysis', 'score'],
    ['section=curation&panel=watermarks', 'curate'],
    ['section=captions', 'captions'],
    ['section=export&panel=backup', 'backup'],
    ['section=export', 'export'],
    ['section=training', 'train'],
    ['section=checkpoints', 'checkpoints'],
    ['section=studio', 'studio'],
  ];
  for (const [query, expected] of cases) {
    assert.equal(legacyWorkspaceStep(new URLSearchParams(query)), expected, query);
  }
});

test('canonical workflow paths include the dataset identity and optional step', () => {
  assert.equal(datasetWorkflowPath(42), '/datasets/42');
  assert.equal(datasetWorkflowPath(42, 'review'), '/datasets/42/review');
  assert.throws(() => datasetWorkflowPath('not-an-id', 'review'), /dataset id/i);
});

test('in-app fix targets route to their owning workflow page', () => {
  assert.equal(workflowStepForTarget('ds-add-import'), 'import');
  assert.equal(workflowStepForTarget('ds-corpus-review'), 'review');
  assert.equal(workflowStepForTarget('gf-reference'), 'reference');
  assert.equal(workflowStepForTarget('gf-generate'), 'generate');
  assert.equal(workflowStepForTarget('gf-images'), 'curate');
  assert.equal(workflowStepForTarget('gf-captions'), 'captions');
  assert.equal(workflowStepForTarget('gf-training'), 'train');
  assert.equal(workflowStepForTarget('unknown-target'), 'curate');
});
