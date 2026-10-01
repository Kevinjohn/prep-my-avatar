import test from 'node:test';
import assert from 'node:assert/strict';
import { createHostedDraft, updateHostedSelection, reviewKey, hostedExportErrors, hostedExportPayload, squareCrop } from './hostedExportModel.js';

const snapshot = { dataset_revision: 'revision-a', subject: { name: 'Demo person', trigger_word: 'demo' }, recipes: [{ id: 'fal-krea-reviewed', version: 1, crop_rule: 'square', input_requirements: { minimum_training_images: 1 }, defaults: { resolution: 1024, steps: 1000, learning_rate: 0.0005, auto_captioning: 'Off', debug_dataset: false } }], images: [{ id: 1, eligible: true, width: 800, height: 1200, original_lineage: 'a' }, { id: 2, eligible: true, width: 800, height: 1200, original_lineage: 'b' }] };
function readyDraft() {
  const draft = createHostedDraft(snapshot);
  draft.subject = { ...draft.subject, consent: true, rights_basis: 'owned', publication_scope: 'Private preparation' };
  draft.selections = [{ image_id: 1, role: 'training', crop: null, caption_override: null }];
  const entry = draft.selections[0];
  entry.approval = { key: reviewKey(draft, entry), image_sha256: 'image-hash', caption_sha256: 'caption-hash', pair_sha256: 'pair-hash' };
  return draft;
}
test('defaults exclude every photo and do not infer consent', () => {
  const draft = createHostedDraft(snapshot);
  assert.deepEqual(draft.selections, []);
  assert.equal(draft.subject.consent, false);
  assert.ok(hostedExportErrors(draft, snapshot).some((error) => error.includes('training')));
});
test('approval becomes stale after crop, caption, role, trigger, recipe or parameter changes', () => {
  const draft = readyDraft();
  assert.deepEqual(hostedExportErrors(draft, snapshot), []);
  for (const patch of [{ crop: [0, 0, 1, 2 / 3] }, { caption_override: 'new caption' }, { role: 'evaluation' }, { burst_group: 'burst' }]) {
    const edited = updateHostedSelection(draft, 0, patch);
    assert.equal(edited.selections[0].approval, undefined);
  }
  for (const edited of [ { ...draft, subject: { ...draft.subject, trigger_word: 'other' } }, { ...draft, parameters: { ...draft.parameters, steps: 100 } }, { ...draft, recipe_version: 2 } ]) {
    assert.ok(hostedExportErrors(edited, snapshot).some((error) => error.includes('review')));
  }
});
test('evaluation rejects original family and burst overlap with creation roles', () => {
  const draft = readyDraft();
  draft.selections.push({ image_id: 2, role: 'evaluation', burst_group: 'same' });
  draft.selections[0].burst_group = 'same';
  assert.ok(hostedExportErrors(draft, snapshot).some((error) => error.includes('burst')));
  const siblings = { ...snapshot, images: snapshot.images.map((image) => ({ ...image, original_lineage: 'a' })) };
  assert.ok(hostedExportErrors(draft, siblings).some((error) => error.includes('source family')));
});
test('payload records excluded IDs, ordered references and exact approval hashes', () => {
  const draft = readyDraft();
  draft.selections.push({ image_id: 1, role: 'reference', reference_role: 'Face identity', reference_order: 2, approval: { image_sha256: 'r1', caption_sha256: 'c1' } }, { image_id: 2, role: 'reference', reference_role: 'Body proportions', reference_order: 1, approval: { image_sha256: 'r2', caption_sha256: 'c2' } });
  const payload = hostedExportPayload(draft, snapshot);
  assert.deepEqual(payload.selections.filter((entry) => entry.role === 'reference').map((entry) => entry.image_id), [2, 1]);
  assert.equal(payload.selections[0].approved_image_sha256, 'image-hash');
  assert.equal(payload.selections[0].approved_pair_sha256, 'pair-hash');
  assert.deepEqual(payload.excluded_image_ids, []);
  assert.equal('approval' in payload.selections[0], false);
});
test('square crop uses actual pixels and refuses invalid coordinates', () => {
  assert.deepEqual(squareCrop({ width: 800, height: 1200 }, { left: 0, top: 200, side: 800 }), [0, 1 / 6, 1, 5 / 6]);
  assert.equal(squareCrop({ width: 800, height: 1200 }, { left: 1, top: 0, side: 800 }), null);
});

test('invalid crop inputs and role-specific exclusions block export', () => {
  const draft = readyDraft();
  draft.selections[0].crop_box = { left: 1000, top: 0, side: 800 };
  assert.ok(hostedExportErrors(draft, snapshot).some((error) => error.includes('invalid square crop')));
  const blocked = { ...snapshot, images: snapshot.images.map((image) => ({ ...image, role_exclusions: { training: 'Hosted rights denied' } })) };
  assert.ok(hostedExportErrors(readyDraft(), blocked).some((error) => error.includes('Hosted rights denied')));
});

test('minimum counts and parameter constraints come from the selected recipe', () => {
  const draft = readyDraft();
  const recipe = { ...snapshot.recipes[0], id: 'alternate-preserve', version: 2, crop_rule: 'preserve', input_requirements: { minimum_training_images: 2 }, parameters: { steps: { type: 'integer', minimum: 10, maximum: 20 } }, defaults: { steps: 15 } };
  const data = { ...snapshot, recipes: [recipe] };
  draft.recipe_id = recipe.id; draft.recipe_version = 2; draft.parameters = { steps: 15 };
  assert.ok(hostedExportErrors(draft, data).some((error) => error.includes('at least 2 training')));
  draft.parameters.steps = 21;
  assert.ok(hostedExportErrors(draft, data).some((error) => error.includes('steps')));
});
