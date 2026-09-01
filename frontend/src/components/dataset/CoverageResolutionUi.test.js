import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const coveragePlan = readFileSync(new URL('./CoveragePlan.jsx', import.meta.url), 'utf8');
const gapResolution = readFileSync(new URL('./CoverageGapResolution.jsx', import.meta.url), 'utf8');
const resolutionModel = readFileSync(new URL('./coverageResolutionModel.js', import.meta.url), 'utf8');
const workspace = readFileSync(new URL('./DatasetWorkspace.jsx', import.meta.url), 'utf8');
const coverageUi = `${coveragePlan}\n${gapResolution}\n${resolutionModel}`;

test('coverage review presents exact primary actions and separates optional opportunities', () => {
  assert.match(coverageUi, /Primary gaps to resolve/);
  assert.match(coverageUi, /primary_actions/);
  assert.match(coverageUi, /shot_label/);
  assert.match(coveragePlan, /Optional variety opportunities/);
  assert.doesNotMatch(coveragePlan, /\.slice\(0, 4\)\.map\(\(item\) => item\.reason\)\.join/);
});

test('coverage gaps require an explicit acknowledgement before continuing', () => {
  assert.match(coverageUi, /Accept remaining gaps/);
  assert.match(coverageUi, /onAcknowledgeGaps/);
  assert.match(workspace, /Continue with unresolved photo-variety gaps\?/);
  assert.match(workspace, /acknowledgeCoverageGaps/);
});
