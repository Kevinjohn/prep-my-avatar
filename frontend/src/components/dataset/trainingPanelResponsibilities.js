export const MAX_PRESET_BYTES = 256 * 1024;

export function parseTrainingPreset(text) {
  const value = JSON.parse(text);
  if (value?.kind !== 'training-preset' || value.version !== 1 || !value.name
      || typeof value.settings !== 'object' || !value.settings
      || Array.isArray(value.settings)) throw new TypeError('unsupported training preset');
  return value;
}

export function normalizeCheckpointPayload(data = {}) {
  const checkpoints = Array.isArray(data.checkpoints) ? data.checkpoints : [];
  const imported = Array.isArray(data.imported) ? data.imported : [];
  const cloudCheckpoints = Array.isArray(data.cloud_checkpoints) ? data.cloud_checkpoints : [];
  return { checkpoints, imported, cloudCheckpoints,
    datasetState: data.dataset_state || null, diskUsage: data.disk_usage || null,
    count: checkpoints.length + imported.length + cloudCheckpoints.length };
}

// Which checkpoints survive a "clean up this run": every final checkpoint of
// the run, plus the 🏆 best-epoch pick if one was scored. If neither exists
// (an unfinished, unscored run), fall back to keeping the last step so the
// button never proposes trashing everything.
export function checkpointsToKeep(checkpoints, bestEpoch) {
  const finals = checkpoints.filter((c) => c.final).map((c) => c.filename);
  const best = bestEpoch?.available ? [bestEpoch.checkpoint] : [];
  const keep = [...new Set([...finals, ...best])];
  if (!keep.length) {
    const last = checkpoints[checkpoints.length - 1];
    if (last) keep.push(last.filename);
  }
  return keep;
}

// The step "Continue training" resumes from: the highest step among this
// run's checkpoints. Assumes `checkpoints` is non-empty — the call site only
// renders the Continue-training button inside a `checkpoints.length > 0`
// guard, so an empty list (Math.max of an empty spread is -Infinity) cannot
// reach here today.
export function nextContinueStep(checkpoints) {
  return Math.max(...checkpoints.map((c) => c.step));
}
