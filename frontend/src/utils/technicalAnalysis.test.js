import test from 'node:test';
import assert from 'node:assert/strict';

import {
  CURRENT_TECHNICAL_ANALYSIS_VERSION,
  technicalAnalysisCounts,
  technicalAnalysisState,
} from './technicalAnalysis.js';

test('technical analysis distinguishes missing, outdated and current rows', () => {
  assert.equal(CURRENT_TECHNICAL_ANALYSIS_VERSION, 2);
  assert.equal(technicalAnalysisState(null).key, 'missing');
  assert.equal(technicalAnalysisState({}).label, 'not analyzed');
  assert.equal(technicalAnalysisState({ face: { quality: 'green' } }).key, 'missing');
  assert.equal(technicalAnalysisState({ analysis_version: 1 }).key, 'outdated');
  assert.equal(technicalAnalysisState({ metrics: { sharpness: 45 } }).key, 'outdated');
  assert.equal(technicalAnalysisState({ analysis_version: 2 }).key, 'current');
  assert.equal(technicalAnalysisState({ analysis_version: 3 }).key, 'current');
});

test('malformed version claims do not become current analysis', () => {
  assert.equal(technicalAnalysisState({ analysis_version: '2' }).key, 'missing');
  assert.equal(technicalAnalysisState({ analysis_version: NaN }).key, 'missing');
  assert.equal(technicalAnalysisState({ analysis_version: 2.5 }).key, 'missing');
  assert.equal(technicalAnalysisState({
    analysis_version: '2', metrics: { sharpness: 80 },
  }).key, 'outdated');
});

test('technical analysis counts use the same state contract', () => {
  assert.deepEqual(technicalAnalysisCounts([
    { analysis: null },
    { analysis: { face: { quality: 'green' } } },
    { analysis: { analysis_version: 1 } },
    { analysis: { analysis_version: 2 } },
    { analysis: { analysis_version: 9 } },
  ]), { missing: 2, outdated: 1, current: 2, total: 5 });
  assert.deepEqual(technicalAnalysisCounts(null), {
    missing: 0, outdated: 0, current: 0, total: 0,
  });
});
