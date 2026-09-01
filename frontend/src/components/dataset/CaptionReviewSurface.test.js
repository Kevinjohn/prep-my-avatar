import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const workspace = fs.readFileSync(new URL('./DatasetWorkspace.jsx', import.meta.url), 'utf8');
const grid = fs.readFileSync(new URL('./DatasetGrid.jsx', import.meta.url), 'utf8');
const tile = fs.readFileSync(new URL('./DatasetGridItem.jsx', import.meta.url), 'utf8');

test('caption step renders every kept image in a caption-only review surface', () => {
  assert.match(workspace, /images\.filter\(\(image\) => image\.status === 'keep' && image\.filename\)/);
  assert.match(workspace, /reviewOnly/);
  assert.match(grid, /reviewOnly=\{reviewOnly\}/);
});

test('read-only workflow tiles hide curation and destructive controls', () => {
  assert.match(tile, /!reviewOnly && url/);
  assert.match(tile, /reviewOnly \? null/);
  assert.match(tile, /!reviewOnly && !isRescueDerived/);
});

test('face-score step shows kept-photo evidence instead of only the run button', () => {
  assert.match(workspace, /stepCls\('curate', 'score'\)/);
  assert.match(workspace, /activeStep\.slug === 'score'[\s\S]*?image\.status === 'keep'/);
  assert.match(workspace, /showCaptions=\{activeStep\.slug !== 'score'\}/);
  assert.match(workspace, /not analyzed/);
  assert.match(grid, /onBatch && !reviewOnly/);
});
