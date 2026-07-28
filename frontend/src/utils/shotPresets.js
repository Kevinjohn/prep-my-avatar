export const SHOT_PRESETS_STORAGE_KEY = 'datasetCustomPresetsV1';
export const CUSTOM_SHOTS_STORAGE_KEY = 'datasetCustomShots';
const STORAGE_VERSION = 1;

export class ShotPresetValidationError extends Error {
  constructor(code, message) {
    super(message);
    this.name = 'ShotPresetValidationError';
    this.code = code;
  }
}

const cleanShot = (shot) => {
  if (!shot || typeof shot !== 'object' || typeof shot.id !== 'string'
      || typeof shot.label !== 'string' || typeof shot.prompt !== 'string'
      || !['face', 'bust', 'body', 'back'].includes(shot.framing)) return null;
  return { id: shot.id, label: shot.label, prompt: shot.prompt, framing: shot.framing,
    ...(shot.nsfw ? { nsfw: true } : {}) };
};

export function loadCustomShots(storage = globalThis.localStorage) {
  try {
    const payload = JSON.parse(storage?.getItem(CUSTOM_SHOTS_STORAGE_KEY) || 'null');
    // The original format was a bare array. Continue reading it while all new
    // writes use an explicit version envelope.
    const shots = Array.isArray(payload)
      ? payload
      : payload?.version === STORAGE_VERSION && Array.isArray(payload.shots) ? payload.shots : [];
    return shots.map(cleanShot).filter(Boolean);
  } catch {
    return [];
  }
}

export function persistCustomShots(storage, shots) {
  storage?.setItem(CUSTOM_SHOTS_STORAGE_KEY, JSON.stringify({
    version: STORAGE_VERSION,
    shots: (Array.isArray(shots) ? shots : []).map(cleanShot).filter(Boolean),
  }));
}

const cleanPreset = (preset) => {
  if (!preset || typeof preset !== 'object' || typeof preset.id !== 'string'
      || typeof preset.name !== 'string' || !preset.name.trim()
      || !Array.isArray(preset.selectedIds) || !preset.selectedIds.every((id) => typeof id === 'string')) return null;
  return {
    id: preset.id,
    name: preset.name.trim(),
    selectedIds: [...new Set(preset.selectedIds)],
    customShots: Array.isArray(preset.customShots) ? preset.customShots.map(cleanShot).filter(Boolean) : [],
  };
};

export function loadShotPresets(storage = globalThis.localStorage) {
  try {
    const payload = JSON.parse(storage?.getItem(SHOT_PRESETS_STORAGE_KEY) || 'null');
    if (!payload || payload.version !== STORAGE_VERSION || !Array.isArray(payload.presets)) return [];
    return payload.presets.map(cleanPreset).filter(Boolean);
  } catch {
    return [];
  }
}

export function persistShotPresets(storage, presets) {
  storage?.setItem(SHOT_PRESETS_STORAGE_KEY, JSON.stringify({ version: STORAGE_VERSION, presets }));
}

const validName = (presets, name, exceptId = null) => {
  const value = String(name || '').trim();
  if (!value) throw new ShotPresetValidationError('empty_name', 'Preset name cannot be empty.');
  if (presets.some((item) => item.id !== exceptId && item.name.trim().toLocaleLowerCase() === value.toLocaleLowerCase())) {
    throw new ShotPresetValidationError('duplicate_name', `A preset named “${value}” already exists.`);
  }
  return value;
};

const makeId = () => globalThis.crypto?.randomUUID?.() || `preset_${Date.now()}_${Math.random().toString(36).slice(2)}`;

export function saveShotPreset(presets, name, selectedIds, customShots) {
  const cleanIds = [...new Set(Array.from(selectedIds || []).filter((id) => typeof id === 'string'))];
  if (!cleanIds.length) throw new ShotPresetValidationError('empty_selection', 'The shot selection cannot be empty.');
  const value = validName(presets, name);
  const selected = new Set(cleanIds);
  return [...presets, {
    id: makeId(), name: value, selectedIds: cleanIds,
    customShots: (customShots || []).filter((shot) => selected.has(shot.id)).map(cleanShot).filter(Boolean),
  }];
}

export function applyShotPreset(preset, customShots, availableIds = null) {
  const current = Array.isArray(customShots) ? customShots : [];
  const known = new Set(current.map((shot) => shot.id));
  const restored = [...current];
  for (const shot of preset.customShots || []) {
    const clean = cleanShot(shot);
    if (clean && !known.has(clean.id)) { restored.push(clean); known.add(clean.id); }
  }
  const resolvable = availableIds == null
    ? null
    : new Set([...availableIds, ...restored.map((shot) => shot.id)]);
  const selectedIds = resolvable == null
    ? [...preset.selectedIds]
    : preset.selectedIds.filter((id) => resolvable.has(id));
  return {
    selectedIds,
    customShots: restored,
    droppedIds: resolvable == null ? [] : preset.selectedIds.filter((id) => !resolvable.has(id)),
  };
}

export function renameShotPreset(presets, id, name) {
  const value = validName(presets, name, id);
  return presets.map((preset) => preset.id === id ? { ...preset, name: value } : preset);
}

export function deleteShotPreset(presets, id) {
  return presets.filter((preset) => preset.id !== id);
}
