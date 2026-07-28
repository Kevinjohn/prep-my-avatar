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
