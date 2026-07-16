export const KLEIN_IMAGE_IMPROVE = 'klein_image_improve';

function resolvedChoice(original, candidates) {
  if (!candidates.length) return null;
  const terminal = candidates.every((candidate) => ['keep', 'reject'].includes(candidate.status));
  const kept = candidates.filter((candidate) => candidate.status === 'keep');
  if (original.status === 'keep' && terminal && kept.length === 0) return 'original';
  if (original.status === 'reject' && terminal && kept.length === 1) return 'improved';
  if (original.status === 'reject' && terminal && kept.length === 0) return 'reject';
  return null;
}

function reviewCandidate(candidates) {
  const kept = candidates.find((candidate) => candidate.status === 'keep');
  if (kept) return kept;
  return [...candidates].sort((a, b) => {
    const aReady = a.filename ? 1 : 0;
    const bReady = b.filename ? 1 : 0;
    return bReady - aReady || Number(b.id || 0) - Number(a.id || 0);
  })[0];
}

export function buildImageImprovementPairs(images = []) {
  const rows = Array.isArray(images) ? images : [];
  const byId = new Map(rows.map((image) => [image.id, image]));
  const groups = new Map();
  for (const candidate of rows.filter((image) => image.derivation_kind === KLEIN_IMAGE_IMPROVE)) {
    const original = byId.get(candidate.parent_image_id);
    // Orphaned rows from older releases remain ordinary, cleanable corpus rows.
    if (!original) continue;
    if (!groups.has(original.id)) groups.set(original.id, { original, candidates: [] });
    groups.get(original.id).candidates.push(candidate);
  }
  return [...groups.values()].map(({ original, candidates }) => {
    const choice = resolvedChoice(original, candidates);
    const candidate = reviewCandidate(candidates);
    const phase = candidate.status === 'failed'
      ? 'failed' : candidate.filename ? 'ready' : 'queued';
    return {
      original,
      candidate,
      candidates,
      imageIds: [original.id, ...candidates.map((item) => item.id)],
      choice,
      phase,
      resolved: choice !== null,
    };
  });
}

/** Unresolved pairs belong only in side-by-side review; resolved pairs expose one winner. */
export function filterImageImprovementGrid(images = []) {
  const pairs = buildImageImprovementPairs(images);
  const pairedIds = new Set(pairs.flatMap((pair) => pair.imageIds));
  const winnerIds = new Set();
  for (const pair of pairs) {
    if (pair.choice === 'original') winnerIds.add(pair.original.id);
    if (pair.choice === 'improved') winnerIds.add(pair.candidate.id);
  }
  return images.filter((image) => !pairedIds.has(image.id) || winnerIds.has(image.id));
}
