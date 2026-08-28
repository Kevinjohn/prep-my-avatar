export const CURRENT_TECHNICAL_ANALYSIS_VERSION = 2;

const STATES = Object.freeze({
  missing: Object.freeze({ key: 'missing', label: 'not analyzed' }),
  outdated: Object.freeze({ key: 'outdated', label: 'outdated' }),
  current: Object.freeze({ key: 'current', label: 'current' }),
});

export function technicalAnalysisState(analysis) {
  const value = analysis && typeof analysis === 'object' && !Array.isArray(analysis)
    ? analysis
    : {};
  const version = value.analysis_version;
  if (Number.isInteger(version) && version >= CURRENT_TECHNICAL_ANALYSIS_VERSION) {
    return STATES.current;
  }
  if (Number.isInteger(version) && version > 0) return STATES.outdated;
  // Very old technical rows can predate the version marker. A face-only result
  // is not technical analysis, so only a metrics object makes that row stale.
  if (value.metrics && typeof value.metrics === 'object' && !Array.isArray(value.metrics)) {
    return STATES.outdated;
  }
  return STATES.missing;
}

export function technicalAnalysisCounts(images) {
  const counts = { missing: 0, outdated: 0, current: 0, total: 0 };
  for (const image of Array.isArray(images) ? images : []) {
    counts[technicalAnalysisState(image?.analysis).key] += 1;
    counts.total += 1;
  }
  return counts;
}
