const arrays = ['selCps', 'selSts', 'selModels', 'selAspects', 'selCfgs', 'selSteps', 'selSteps2'];

export function decodeStudioForm(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
  const out = {};
  for (const key of arrays) {
    if (raw[key] == null) continue;
    if (Array.isArray(raw[key])) out[key] = raw[key];
  }
  if (Number.isSafeInteger(raw.seed) && raw.seed >= 0 && raw.seed < 2 ** 31) out.seed = raw.seed;
  if (typeof raw.seedLocked === 'boolean') out.seedLocked = raw.seedLocked;
  if (Number.isInteger(raw.genCount) && raw.genCount >= 1 && raw.genCount <= 4) out.genCount = raw.genCount;
  if (raw.promptText === null || typeof raw.promptText === 'string') out.promptText = raw.promptText;
  return out;
}

export function groupStudioRuns(cells = []) {
  const groups = new Map();
  for (const cell of cells) {
    const runSeed = cell.run_seed ?? cell.seed;
    const key = cell.run_id || `${runSeed}|${cell.prompt || ''}`;
    let group = groups.get(key);
    if (!group) {
      group = { key, seed: runSeed, prompt: cell.prompt || '', models: new Set(),
        cells: [], latestId: 0, likes: 0, dislikes: 0 };
      groups.set(key, group);
    }
    group.cells.push(cell);
    if (cell.z_model_label) group.models.add(cell.z_model_label);
    if (cell.id > group.latestId) group.latestId = cell.id;
    if (cell.rating === 1) group.likes += 1;
    else if (cell.rating === -1) group.dislikes += 1;
  }
  return [...groups.values()].map((group) => ({
    ...group,
    modelLabel: group.models.size > 1 ? `${group.models.size} models` : ([...group.models][0] || ''),
  })).sort((a, b) => b.latestId - a.latestId);
}
