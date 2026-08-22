const DATASET_CURRENT_ID_KEY = 'datasetCurrentId';

/**
 * Best-effort channel for the open dataset: useDataset reads it at mount to
 * restore the workspace after a reload, while other pages write it before
 * navigation to hand that workspace over. Clearing it returns home to the
 * dataset list. Storage failures must never interrupt any of those flows.
 */
export function readDatasetCurrentId() {
  try {
    const value = globalThis.localStorage.getItem(DATASET_CURRENT_ID_KEY);
    return value ? Number(value) : null;
  } catch {
    return null;
  }
}

export function writeDatasetCurrentId(id) {
  try {
    globalThis.localStorage.setItem(DATASET_CURRENT_ID_KEY, String(id));
  } catch { /* storage is best-effort */ }
}

export function clearDatasetCurrentId() {
  try {
    globalThis.localStorage.removeItem(DATASET_CURRENT_ID_KEY);
  } catch { /* storage is best-effort */ }
}
