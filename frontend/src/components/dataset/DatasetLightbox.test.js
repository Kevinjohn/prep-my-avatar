import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const lightbox = readFileSync(new URL('./DatasetLightbox.jsx', import.meta.url), 'utf8');
const workspace = readFileSync(new URL('./DatasetWorkspace.jsx', import.meta.url), 'utf8');
const hook = readFileSync(new URL('../../hooks/useDataset.js', import.meta.url), 'utf8');
const settings = readFileSync(new URL('../settings/ScrapingSection.jsx', import.meta.url), 'utf8');
const improvementReview = readFileSync(new URL('./ImageImprovementReview.jsx', import.meta.url), 'utf8');

test('lightbox exposes an accessible responsive image improvement action', () => {
  assert.match(lightbox, /🔬 Reconstruct & compare/);
  assert.match(lightbox, /🔬 Reconstructing…/);
  assert.match(lightbox, /Review improvement first/);
  assert.match(lightbox, /aria-busy=\{improvementActive\}/);
  assert.match(lightbox, /w-full sm:w-auto/);
  assert.match(lightbox, /Klein reconstructs from the preserved original with identity references/);
  assert.match(lightbox, /admit exactly one/);
  assert.match(lightbox, /busy \|\| improvementActive \|\| improveReady \|\| !kleinAvailable/);
});

test('workspace guards rescue rows and detects a pending improvement child', () => {
  assert.match(workspace, /!viewImgLive\._rescueReviewPreview/);
  assert.match(workspace, /!viewImgLive\._imageImprovementReviewPreview/);
  assert.match(workspace, /!isSmallImageRescueRow\(viewImgLive\)/);
  assert.match(workspace, /viewImgLive\.derivation_kind !== 'klein_image_improve'/);
  assert.match(workspace, /image\.derivation_kind === 'klein_image_improve'/);
  assert.match(workspace, /image\.parent_image_id === viewImgLive\.id/);
  assert.match(workspace, /const viewImgImproving[\s\S]*image\.status === 'pending'[\s\S]*\)\) : false/);
  assert.match(workspace, /const viewImgImprovementReady[\s\S]*image\.status === 'pending'[\s\S]*!!image\.filename/);
  assert.match(workspace, /kleinAvailable=\{Boolean\(caps\.engines\?\.klein\)\}/);
});

test('dataset hook starts improvement and follows reconstruction changes via the shared event stream', () => {
  assert.match(hook, /`\/api\/dataset\/image\/\$\{imageId\}\/improve`, \{\}/);
  assert.match(hook, /Reconstruction started from the preserved original/);
  assert.match(hook, /Could not start image improvement/);
  assert.match(hook, /resolveSmallImageRescue, improveImage, resolveImageImprovement/);
  assert.match(hook, /new EventSource\(`\/api\/dataset\/\$\{currentId\}\/events`\)/);
  assert.match(hook, /source\.addEventListener\('dataset'/);
});

test('settings explains the shared instruction for scraper and lightbox improvement', () => {
  assert.match(settings, /title="Klein image improvement"/);
  assert.match(settings, /automatic rescue of scraped images under 768 px/);
  assert.match(settings, /Manual Reconstruct & compare/);
  assert.match(settings, /exact source pixels/);
});

test('manual improvement candidates cannot use the unrelated generic regenerate path', () => {
  const gridItem = readFileSync(new URL('./DatasetGridItem.jsx', import.meta.url), 'utf8');
  assert.match(gridItem, /const isImageImproveCandidate = img\.derivation_kind === 'klein_image_improve'/);
  assert.match(gridItem, /!isRescueDerived && !isImageImproveCandidate && img\.source === 'generated'/);
  assert.match(gridItem, /if \(!isImageImproveCandidate && img\.status !== 'reject'/);
});

test('reconstruction review renders the exact input and freezes both previews', () => {
  assert.match(improvementReview, /comparison\.source_filename/);
  assert.match(improvementReview, /Exact reconstruction input/);
  assert.match(improvementReview, /_imageImprovementReviewPreview: true/);
  assert.match(workspace, /viewImgLive\._rescueReviewPreview \|\| viewImgLive\._imageImprovementReviewPreview/);
  assert.match(improvementReview, /Automatic comparison failed:/);
});
