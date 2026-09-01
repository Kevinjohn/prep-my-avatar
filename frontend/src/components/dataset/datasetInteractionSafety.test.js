import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = (name) => readFileSync(new URL(name, import.meta.url), 'utf8');

test('bulk curation keeps the selection unless every requested image was updated', () => {
  const grid = source('./DatasetGrid.jsx');
  assert.match(grid, /const affected = await onBatch\(ids, action\)/);
  assert.match(grid, /if \(affected === ids\.length\)/);
  assert.match(grid, /The bulk action failed\. Your selection was kept/);
});

test('late Hugging Face prefill cannot replace a repository edited by the user', () => {
  const modal = source('./PublishHfModal.jsx');
  assert.match(modal, /repoIdDirtyRef\.current = true/);
  assert.match(modal, /d\.default_repo_id && !repoIdDirtyRef\.current/);
});

test('variation catalog exposes retry, storage failure, and stale-preset recovery', () => {
  const catalog = source('./VariationCatalog.jsx');
  const controller = source('../../hooks/useVariationCatalogController.js');
  const persistence = source('../../hooks/useShotPersistence.js');
  assert.match(catalog, /Variation catalog could not be loaded/);
  assert.match(catalog, /setCatalogAttempt\(\(attempt\) => attempt \+ 1\)/);
  assert.match(persistence, /session-only because browser storage is unavailable/);
  assert.match(controller, /applyShotPreset\(preset, customShots, availableIds\)/);
  assert.match(controller, /no longer exist and were removed from this selection/);
  assert.match(catalog, /Local generation failed/);
  assert.match(catalog, /img\.fail_reason/);
});

test('remote engine cards distinguish provider readiness from privacy approval', () => {
  const catalog = source('./VariationCatalog.jsx');
  const engines = source('../../hooks/useVariationEngines.js');
  const controller = source('../../hooks/useVariationCatalogController.js');
  assert.match(engines, /nbProviderReady/);
  assert.match(engines, /gptProviderReady/);
  assert.match(controller, /nbProviderReady, gptProviderReady, nanoBananaProviderLabel/);
  assert.match(catalog, /Ready via \{nanoBananaProviderLabel\}/);
  assert.match(catalog, /Connected · \{gptPlanLabel\} subscription/);
  assert.match(catalog, /Generate will ask for batch approval/);
  assert.match(controller, /selected reference image/);
  assert.match(controller, /prompt.*to \$\{destination\}/);
  assert.match(controller, /approveRemoteGeneration/);
  assert.match(catalog, /disabled=\{!nbProviderReady/);
  assert.match(catalog, /disabled=\{!gptProviderReady/);
});

test('duplicate-shot protection uses authoritative whole-dataset counts', () => {
  const controller = source('../../hooks/useVariationCatalogController.js');
  const workspace = source('./DatasetWorkspace.jsx');
  assert.match(controller, /new Map\(Object\.entries\(variationLabelCounts\)\)/);
  assert.match(controller, /hasOwnProperty\.call\(variationLabelCounts, img\.variation_label\)/);
  assert.match(workspace, /variationLabelCounts=\{d\.image_summary\?\.variation_label_counts\}/);
});

test('unavailable Klein setup is a sibling of the disabled selection button', () => {
  const catalog = source('./VariationCatalog.jsx');
  const kleinCard = catalog.slice(catalog.indexOf('<div className={`flex items-start'), catalog.indexOf("setGenerator('nanobanana')"));
  assert.match(kleinCard, /<\/button>\s*\{!klAvailable && \(\s*<a href="#\/setup"/);
  assert.doesNotMatch(kleinCard, /<a href="#\/setup"[\s\S]*<\/a>[\s\S]*<\/button>/);
});

test('lightbox zoom and prompt editing expose keyboard-operable dialog controls', () => {
  const lightbox = source('./DatasetLightbox.jsx');
  const popover = source('./PromptEditPopover.jsx');
  assert.match(lightbox, /aria-label=\{full \? 'Fit image to screen' : 'Zoom image to 100 percent'\}/);
  assert.match(lightbox, /aria-pressed=\{full\}/);
  assert.match(popover, /useFocusTrap\(dialogRef, true\)/);
  assert.match(popover, /role="dialog" aria-modal="true" aria-labelledby="prompt-edit-title"/);
});

test('failed crop persistence keeps each crop editor open for retry', () => {
  const workspace = source('./DatasetWorkspace.jsx');
  const hook = source('../../hooks/useDataset.js');
  assert.match(workspace, /if \(await ds\.crop\(cropImg\.id, box\)\) setCropImg\(null\)/);
  assert.match(workspace, /if \(await ds\.cropRef\(box\)\) setRefCrop\(false\)/);
  assert.match(workspace, /if \(await ds\.recropRefAuto\(\)\) setRefCrop\(false\)/);
  assert.match(hook, /const crop = useCallback[\s\S]*return false;[\s\S]*return true;/);
  assert.match(hook, /const cropRef = useCallback[\s\S]*return false;[\s\S]*return true;/);
});

test('style datasets never present the internal identifier as a prompt trigger', () => {
  const workspace = source('./DatasetWorkspace.jsx');
  const settings = source('./DatasetSettingsModal.jsx');
  assert.match(workspace, /d\.kind !== 'style'/);
  assert.match(workspace, /Style LoRA · no prompt trigger/);
  assert.match(settings, /const style = d\.kind === 'style'/);
  assert.match(settings, /trigger_word: style \? undefined : trigger\.trim\(\)/);
  assert.match(settings, /Style LoRAs apply their aesthetic when loaded and do not use a prompt trigger/);
});

test('dataset kind and character fidelity expose their selected state', () => {
  const panel = source('./DatasetListPanel.jsx');
  assert.match(panel, /role="group" aria-label="Dataset kind"/);
  assert.match(panel, /aria-pressed=\{kind === val\}/);
  assert.match(panel, /role="group" aria-label="Character fidelity"/);
  assert.match(panel, /aria-pressed=\{fidelity === val\}/);
});

test('trigger copy awaits the clipboard and reports both outcomes', () => {
  const workspace = source('./DatasetWorkspace.jsx');
  assert.match(workspace, /await navigator\.clipboard\.writeText/);
  assert.match(workspace, /Trigger word copied/);
  assert.match(workspace, /Could not copy the trigger word/);
});

test('settings owns its pending state and prevents duplicate submission or close', () => {
  const settings = source('./DatasetSettingsModal.jsx');
  assert.match(settings, /const \[submitting, setSubmitting\] = useState\(false\)/);
  assert.match(settings, /if \(!canSave \|\| pending\) return/);
  assert.match(settings, /setSubmitting\(true\)[\s\S]*finally[\s\S]*setSubmitting\(false\)/);
  assert.match(settings, /disabled=\{!canSave \|\| pending\}/);
});

test('training evidence is complete and zero-step progress remains visible', () => {
  const feedback = source('./TrainingFeedbackPanel.jsx');
  const progress = source('./TrainingProgress.jsx');
  assert.match(feedback, /\{runs\.map\(\(run\) => \(/);
  assert.doesNotMatch(feedback, /runs\.slice/);
  assert.match(progress, /Number\.isFinite\(step\).*Number\.isFinite\(total\).*total > 0/);
  assert.match(progress, /const pct = hasProgress/);
  assert.match(progress, /Math\.max\(0, Math\.min\(step, total\)\)/);
});
