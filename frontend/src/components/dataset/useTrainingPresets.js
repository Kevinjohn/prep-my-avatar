import { useEffect, useMemo, useState } from 'react';
import { getJson, safeDeleteJson } from '../../api/fetchClient';
import { MAX_PRESET_BYTES, parseTrainingPreset } from './trainingPanelResponsibilities';

/** Owns preset persistence and selection; rendering stays in TrainingPresetControls. */
export function useTrainingPresets({ datasetId, trainType, setAdvancedSettings,
  toast, confirm, promptDialog, postTrain, reportError }) {
  const [presets, setPresets] = useState([]);
  const [selectedId, setSelectedId] = useState('');
  const selectedPreset = useMemo(
    () => presets.find((preset) => String(preset.id) === selectedId) || null,
    [presets, selectedId],
  );
  const refresh = async () => {
    try { setPresets((await getJson('/api/train/presets')).presets || []); } catch { /* best effort */ }
  };
  useEffect(() => { refresh(); }, []);

  const save = async () => {
    const name = await promptDialog({ title: 'Save training preset',
      message: 'If a preset already has this name, its settings will be overwritten.',
      inputLabel: 'Preset name', confirmLabel: 'Save preset' });
    if (!name?.trim()) return;
    const result = await postTrain('/api/train/presets',
      { name: name.trim(), dataset_id: datasetId, train_type: trainType });
    if (result.ok === false) return reportError(result, 'Preset save failed');
    toast.success(`Preset “${name.trim()}” saved.`); refresh();
  };
  const apply = async () => {
    if (!selectedPreset) return;
    const result = await postTrain(`/api/dataset/${datasetId}/train/presets/apply`,
      selectedPreset.builtin ? { settings: selectedPreset.settings } : { preset_id: selectedPreset.id });
    if (result.ok === false) return reportError(result, 'Preset apply failed');
    setAdvancedSettings(result.train_settings);
    const notes = [];
    if (result.ignored?.length) notes.push(`unknown here, ignored: ${result.ignored.join(', ')}`);
    if (result.rejected?.length) notes.push(`rejected: ${result.rejected.map((item) => item.key).join(', ')}`);
    if (notes.length) toast.warning(`Preset applied — ${notes.join(' · ')}`);
    else toast.success(`Preset “${selectedPreset.name}” applied.`);
  };
  const importFile = async (file) => {
    if (!file || file.size > MAX_PRESET_BYTES) return toast.error('Preset files must be 256 KB or smaller.');
    try {
      const value = parseTrainingPreset(await file.text());
      const result = await postTrain('/api/train/presets',
        { name: String(value.name), train_type: value.train_type || trainType, settings: value.settings });
      if (result.ok === false) return reportError(result, 'Preset import failed');
      toast.success(`Preset “${value.name}” imported — select it and Apply.`); refresh();
    } catch (error) {
      toast.error(error instanceof SyntaxError ? 'Unreadable preset file.'
        : 'Not a supported training preset (expected kind "training-preset", version 1).');
    }
  };
  const remove = async () => {
    if (!selectedPreset || selectedPreset.builtin) return;
    if (!(await confirm({ title: `Delete preset “${selectedPreset.name}”?`,
      message: 'The saved training settings will be removed. Existing runs and checkpoints are unaffected.',
      confirmLabel: 'Delete preset', tone: 'danger' }))) return;
    const result = await safeDeleteJson(`/api/train/presets/${selectedPreset.id}`);
    if (!result.ok) return reportError(result, 'Preset deletion failed');
    setSelectedId(''); refresh();
  };
  const exportPreset = () => {
    if (!selectedPreset) return;
    const blob = new Blob([JSON.stringify({ app: 'lora-dataset-studio',
      kind: 'training-preset', version: 1, name: selectedPreset.name,
      train_type: selectedPreset.train_type, settings: selectedPreset.settings }, null, 2)],
    { type: 'application/json' });
    const anchor = document.createElement('a');
    anchor.href = URL.createObjectURL(blob);
    anchor.download = `lds-training-preset-${selectedPreset.name.replace(/[^\w.-]+/g, '_')}.json`;
    anchor.click(); URL.revokeObjectURL(anchor.href);
  };
  return { presets, selectedId, setSelectedId, selectedPreset, save, apply,
    importFile, remove, export: exportPreset };
}
