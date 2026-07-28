import { useRef } from 'react';

/** @param {{controller: ReturnType<import('./useTrainingPresets').useTrainingPresets>}} props */
export default function TrainingPresetControls({ controller }) {
  const fileRef = useRef(null);
  const { presets, selectedId, setSelectedId, selectedPreset } = controller;
  return (
    <div className="flex items-center gap-1.5 flex-wrap rounded-lg border border-border bg-app/40 px-2 py-1.5">
      <span className="text-content-muted text-[0.625rem] uppercase">Presets</span>
      <select value={selectedId} onChange={(event) => setSelectedId(event.target.value)}
        aria-label="Training preset" className="px-2 py-1 rounded-lg border border-border bg-surface text-content text-[0.75rem] max-w-[220px]">
        <option value="">— pick a preset —</option>
        {presets.map((preset) => <option key={preset.id} value={preset.id}>
          {preset.builtin ? '★ ' : ''}{preset.name} ({preset.train_type})
        </option>)}
      </select>
      <button type="button" onClick={controller.apply} disabled={!selectedPreset}
        title="Replace this dataset's advanced settings with the selected preset"
        className="px-2.5 py-1 rounded-lg bg-primary/20 border border-primary/40 text-white text-[0.75rem] font-semibold disabled:opacity-40">
        Apply
      </button>
      <span className="mx-0.5 text-content-subtle" aria-hidden>·</span>
      <button type="button" onClick={controller.save}
        title="Save this dataset's current advanced settings as a named preset"
        className="px-2.5 py-1 rounded-lg bg-surface-raised border border-border text-content text-[0.75rem]">
        💾 Save current…
      </button>
      <button type="button" onClick={() => fileRef.current?.click()}
        title="Import a preset from a JSON file (exported from any app version — unknown options are ignored at apply time)"
        className="px-2.5 py-1 rounded-lg bg-surface-raised border border-border text-content text-[0.75rem]">
        ⬆ Import
      </button>
      <button type="button" onClick={controller.export} disabled={!selectedPreset}
        title="Download the selected preset as a shareable JSON file"
        className="px-2.5 py-1 rounded-lg bg-surface-raised border border-border text-content text-[0.75rem] disabled:opacity-40">
        ⬇ Export
      </button>
      <button type="button" onClick={controller.remove} disabled={!selectedPreset || selectedPreset.builtin}
        title={selectedPreset?.builtin ? 'Built-in presets ship with the app and cannot be deleted' : 'Delete the selected preset'}
        className="px-2 py-1 rounded-lg bg-red-500/15 border border-red-500/40 text-red-300 text-[0.75rem] disabled:opacity-40">
        🗑
      </button>
      <input ref={fileRef} type="file" accept=".json,application/json" className="hidden"
        onChange={(event) => { const file = event.target.files?.[0]; if (file) controller.importFile(file); event.target.value = ''; }} />
    </div>
  );
}
