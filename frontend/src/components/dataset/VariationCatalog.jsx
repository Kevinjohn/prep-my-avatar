/** Variation catalog: presets + per-entry toggles + multiplier + Klein picker. */
import Flux2KleinModelPicker from '../shared/Flux2KleinModelPicker';
import ShotIllustration, { contextEmoji } from './ShotIllustration';
import { displayLabel } from '../../utils/labels';
import { useVariationCatalogController } from '../../hooks/useVariationCatalogController';
import {
  DEFAULT_COVERAGE_TARGET as TARGET, FRAMING_COLOR, FRAMING_LABEL, FRAMING_ORDER, PRESET_META,
} from './variationCatalogModel';

/** Mini stacked bar showing a preset's framing mix (face/bust/body/back). */
function CompositionMiniBar({ counts, total }) {
  if (!total) return null;
  return (
    <span className="flex h-1.5 w-full rounded-full overflow-hidden bg-app/60" aria-hidden="true">
      {FRAMING_ORDER.map((fr) => counts[fr] ? (
        <span key={fr} className={FRAMING_COLOR[fr]} style={{ width: `${(counts[fr] / total) * 100}%` }} />
      ) : null)}
    </span>
  );
}

/** Minimal ChatGPT pictogram — hexagonal knot silhouette, currentColor. */
function ChatGptIcon({ className }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true" focusable="false">
      {[0, 60, 120, 180, 240, 300].map((a) => (
        <path key={a} transform={`rotate(${a} 16 16)`}
          d="M16 4.5 a 6.2 6.2 0 0 1 6.2 6.2 v 4 l -3.4 -2 v -2 a 2.8 2.8 0 0 0 -2.8 -2.8 z"
          fill="currentColor" />
      ))}
      <circle cx="16" cy="16" r="3.1" fill="none" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  );
}

/** Small inline GPU-chip pictogram for the local Klein engine card. */
function GpuIcon({ className }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true" focusable="false">
      <rect x="7" y="7" width="18" height="18" rx="3" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <rect x="12" y="12" width="8" height="8" rx="1.5" fill="currentColor" opacity="0.85" />
      {[10, 16, 22].map((p) => (
        <g key={p} stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
          <line x1={p} y1="2.5" x2={p} y2="6" />
          <line x1={p} y1="26" x2={p} y2="29.5" />
          <line x1="2.5" y1={p} x2="6" y2={p} />
          <line x1="26" y1={p} x2="29.5" y2={p} />
        </g>
      ))}
    </svg>
  );
}

export default function VariationCatalog({ onGenerate, busy, generating = null, hasRef,
  hasPrimaryRef = hasRef, composition, images = [], bodyFidelity = false,
  recommendedIds, anchorPlan = null, coverageTargets = TARGET,
  variationLabelCounts = {} }) {
  const {
    nanoBananaRate, chatGptApiRate, pricingAsOf, nsfwCatalog,
    catalogLoadError, setCatalogAttempt, selected, setSelected, multiplier,
    setMultiplier, setKlein, nsfwMode, setNsfwMode, customPrompt,
    setCustomPrompt, customFraming, setCustomFraming, customShots, customPresets,
    storageWarning, addCustomShot, removeCustomShot, loraStrength, setLoraStrength,
    setGenerator, settingsError, remoteAllowed, isNB, isGPT, isKlein,
    nbAvailable, gptAvailable, klAvailable, currentAvailable, gptViaSub, gptPlanLabel,
    kleinHint, byFraming, doneByLabel, presetStats, activePreset, activeCustomPreset,
    customPresetStats, toggle, applyPreset, saveCurrentPreset, applyCustomPreset,
    renameCustomPreset, removeCustomPreset, go,
  } = useVariationCatalogController({ onGenerate, bodyFidelity, recommendedIds,
    images, variationLabelCounts })
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-3">
      <div className="flex items-center gap-2">
        <span aria-hidden="true">🎬</span>
        <h2 className="text-content font-semibold text-sm">Generate variations</h2>
        <span className="text-content-subtle text-[0.6875rem]">
          pick the shots to synthesize from your reference pool
        </span>
        {anchorPlan?.selected_total > 0 && (
          <span className="ml-auto rounded-full border border-emerald-400/40 bg-emerald-500/10 px-2 py-0.5 text-[0.625rem] text-emerald-200">
            ◆ API anchor pack {anchorPlan.selected_total}/{anchorPlan.limit}
          </span>
        )}
      </div>

      {/* Engine cards — Klein (local GPU) vs Nano Banana Pro vs ChatGPT (APIs).
          Each card disables itself with an actionable hint when its engine
          isn't configured/reachable or was turned off in Settings. */}
      <div className="flex items-center gap-2">
        <span className="text-content-muted text-[0.6875rem] uppercase">Engine</span>
        <span className="text-content-subtle text-[0.625rem]">
          where the images are made — Klein runs free on your GPU · APIs bill per image (or use your ChatGPT subscription)
        </span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        <div className={`flex items-start gap-3 rounded-xl border p-3 transition-colors ${isKlein
          ? 'border-primary/60 bg-primary/15 ring-1 ring-primary/40'
          : 'border-border bg-app/40'}`}>
          <button type="button" onClick={() => setGenerator('klein')} aria-pressed={isKlein}
            disabled={!klAvailable || !!generating}
            title={generating ? 'A generation batch is running — wait for it to finish before switching engine' : undefined}
            className="flex min-w-0 flex-1 items-start gap-3 text-left disabled:cursor-not-allowed disabled:opacity-50">
            <GpuIcon className={`w-9 h-9 shrink-0 ${isKlein ? 'text-indigo-300' : 'text-content-subtle'}`} />
            <span className="flex flex-col gap-1 min-w-0">
            <span className={`text-[0.8125rem] font-semibold ${isKlein ? 'text-white' : 'text-content-muted'}`}>
              Klein <span className="font-normal text-content-subtle">· local</span>
            </span>
            <span className="flex flex-wrap gap-1">
              <span className="px-1.5 py-px rounded-full bg-emerald-500/15 border border-emerald-400/40 text-emerald-300 text-[0.625rem]">Free</span>
              <span className="px-1.5 py-px rounded-full bg-app/60 border border-border text-content-muted text-[0.625rem]">Your GPU</span>
              <span className="px-1.5 py-px rounded-full bg-app/60 border border-border text-content-muted text-[0.625rem]">NSFW OK</span>
            </span>
            {klAvailable && (
              <span className="text-content-subtle text-[0.625rem]">Runs on this machine — slower, tunable face fidelity.</span>
            )}
            </span>
          </button>
          {!klAvailable && (
            <a href="#/setup"
              className="text-amber-300 text-[0.625rem] underline decoration-amber-300/50">
              {kleinHint}
            </a>
          )}
        </div>
        <button type="button" onClick={() => setGenerator('nanobanana')} aria-pressed={isNB}
          disabled={!nbAvailable || !!generating}
          title={generating ? 'A generation batch is running — wait for it to finish before switching engine' : undefined}
          className={`flex items-start gap-3 rounded-xl border p-3 text-left transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${isNB
            ? 'border-amber-400/60 bg-amber-500/15 ring-1 ring-amber-400/40'
            : 'border-border bg-app/40 hover:enabled:bg-surface-raised'}`}>
          <span className="w-9 h-9 shrink-0 grid place-items-center text-2xl" aria-hidden="true">🍌</span>
          <span className="flex flex-col gap-1 min-w-0">
            <span className={`text-[0.8125rem] font-semibold ${isNB ? 'text-amber-200' : 'text-content-muted'}`}>
              Nano Banana Pro <span className="font-normal text-content-subtle">· API</span>
            </span>
            <span className="flex flex-wrap gap-1">
              <span className="px-1.5 py-px rounded-full bg-app/60 border border-border text-content-muted text-[0.625rem]">No GPU</span>
              <span className="px-1.5 py-px rounded-full bg-app/60 border border-border text-content-muted text-[0.625rem]">
                ~${nanoBananaRate.toFixed(2)}/image estimate{pricingAsOf ? ` · ${pricingAsOf}` : ''}
              </span>
              <span className="px-1.5 py-px rounded-full bg-app/60 border border-border text-content-muted text-[0.625rem]">SFW</span>
            </span>
            {nbAvailable ? (
              <span className={`text-[0.625rem] ${isNB ? 'text-amber-300' : 'text-content-subtle'}`}>
                Best face fidelity · estimated cost ≈ ${(selected.size * multiplier * nanoBananaRate).toFixed(2)}
              </span>
            ) : (
              <span className="text-amber-300 text-[0.625rem]">
                ⚠ {remoteAllowed ? 'Add GEMINI_API_KEY in Settings' : 'Enable remote generation in Settings ▸ Image engines'}
              </span>
            )}
          </span>
        </button>
        <button type="button" onClick={() => setGenerator('chatgpt')} aria-pressed={isGPT}
          disabled={!gptAvailable || !!generating}
          title={generating ? 'A generation batch is running — wait for it to finish before switching engine' : undefined}
          className={`flex items-start gap-3 rounded-xl border p-3 text-left transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${isGPT
            ? 'border-emerald-400/60 bg-emerald-500/15 ring-1 ring-emerald-400/40'
            : 'border-border bg-app/40 hover:enabled:bg-surface-raised'}`}>
          <ChatGptIcon className={`w-9 h-9 shrink-0 ${isGPT ? 'text-emerald-300' : 'text-content-subtle'}`} />
          <span className="flex flex-col gap-1 min-w-0">
            <span className={`text-[0.8125rem] font-semibold ${isGPT ? 'text-emerald-200' : 'text-content-muted'}`}>
              ChatGPT <span className="font-normal text-content-subtle">{gptViaSub ? '· subscription' : '· API'}</span>
            </span>
            <span className="flex flex-wrap gap-1">
              <span className="px-1.5 py-px rounded-full bg-app/60 border border-border text-content-muted text-[0.625rem]">No GPU</span>
              <span className="px-1.5 py-px rounded-full bg-app/60 border border-border text-content-muted text-[0.625rem]">
                {gptViaSub ? 'Plan quota' : `~$${chatGptApiRate.toFixed(2)}/image estimate${pricingAsOf ? ` · ${pricingAsOf}` : ''}`}
              </span>
              <span className="px-1.5 py-px rounded-full bg-app/60 border border-border text-content-muted text-[0.625rem]">SFW</span>
            </span>
            {gptAvailable ? (
              <span className={`text-[0.625rem] ${isGPT ? 'text-emerald-300' : 'text-content-subtle'}`}>
                {gptViaSub
                  ? `gpt-image-2 · uses your ChatGPT ${gptPlanLabel} quota`
                  : `gpt-image-2 · estimated cost ≈ $${(selected.size * multiplier * chatGptApiRate).toFixed(2)}`}
              </span>
            ) : (
              <span className="text-amber-300 text-[0.625rem]">
                ⚠ {remoteAllowed ? 'Add an API key or connect a subscription in Settings' : 'Enable remote generation in Settings ▸ Image engines'}
              </span>
            )}
          </span>
        </button>
      </div>

      {/* Preset cards with their framing-mix bar. */}
      {catalogLoadError && (
        <div role="alert" className="flex items-center gap-2 rounded border border-red-400/40 bg-red-500/10 px-2 py-1.5 text-xs text-red-200">
          <span>Variation catalog could not be loaded.</span>
          <button type="button" onClick={() => setCatalogAttempt((attempt) => attempt + 1)}
            className="ml-auto rounded border border-red-300/40 px-2 py-0.5 font-semibold hover:bg-red-500/20">
            Retry
          </button>
        </div>
      )}
      {storageWarning && (
        <p role="alert" className="m-0 rounded border border-amber-400/40 bg-amber-500/10 px-2 py-1.5 text-xs text-amber-200">
          Custom shots and presets are session-only. Free browser storage and save again before reloading.
        </p>
      )}
      <div>
        <div className="flex items-center gap-2 mb-1.5 flex-wrap">
          <span className="text-content-muted text-[0.6875rem] uppercase">Presets</span>
          <button type="button" onClick={saveCurrentPreset} disabled={!selected.size}
            aria-label="Save the current shot selection as a custom preset"
            className="rounded-md border border-primary/40 bg-primary/10 px-2 py-1 text-[0.625rem] font-semibold text-indigo-200 hover:bg-primary/20 disabled:opacity-40">
            ＋ Save preset
          </button>
          <span className="ml-auto flex items-center gap-2 flex-wrap text-[0.625rem] text-content-subtle" aria-hidden="true">
            {FRAMING_ORDER.map((fr) => (
              <span key={fr} className="flex items-center gap-1">
                <span className={`w-2 h-2 rounded-full ${FRAMING_COLOR[fr]}`} />{FRAMING_LABEL[fr]}
              </span>
            ))}
          </span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-1.5">
          {PRESET_META.map(({ key, name, hint }) => {
            const st = presetStats[key];
            const active = activePreset === key;
            return (
              <button key={key} type="button" onClick={() => applyPreset(key)} title={hint}
                aria-pressed={active} disabled={!st?.total}
                className={`flex flex-col gap-1.5 rounded-lg border p-2 text-left transition-colors disabled:opacity-40 ${active
                  ? 'border-primary/60 bg-primary/15 ring-1 ring-primary/40'
                  : 'border-border bg-app/40 hover:bg-surface-raised'}`}>
                <span className="flex items-baseline gap-1 min-w-0">
                  <span className={`text-[0.6875rem] font-semibold truncate ${active ? 'text-white' : 'text-content'}`}>{name}</span>
                  <span className="ml-auto text-content-subtle text-[0.625rem] shrink-0">{st?.total || 0}</span>
                </span>
                <CompositionMiniBar counts={st?.counts || {}} total={st?.total || 0} />
              </button>
            );
          })}
          {customPresets.map((preset) => {
            const active = activeCustomPreset === preset.id;
            const st = customPresetStats[preset.id];
            return (
              <div key={preset.id}
                className={`relative min-w-0 rounded-lg border transition-colors ${active
                  ? 'border-primary/60 bg-primary/15 ring-1 ring-primary/40'
                  : 'border-border bg-app/40 hover:bg-surface-raised'}`}>
                <button type="button" onClick={() => applyCustomPreset(preset)} aria-pressed={active}
                  aria-label={`Apply custom preset ${preset.name}`}
                  className="flex w-full min-w-0 flex-col gap-1.5 p-2 pr-12 text-left">
                  <span className="flex w-full min-w-0 items-baseline gap-1">
                    <span className={`truncate text-[0.6875rem] font-semibold ${active ? 'text-white' : 'text-content'}`}>
                      ✨ {preset.name}
                    </span>
                    <span className="ml-auto shrink-0 text-[0.625rem] text-content-subtle">{st?.total || 0}</span>
                  </span>
                  <CompositionMiniBar counts={st?.counts || {}} total={st?.total || 0} />
                </button>
                <div className="absolute right-1 top-1 flex gap-0.5">
                  <button type="button" onClick={() => renameCustomPreset(preset)}
                    aria-label={`Rename custom preset ${preset.name}`} title="Rename preset"
                    className="grid h-5 w-5 place-items-center rounded text-[0.625rem] text-content-subtle hover:bg-white/10 hover:text-content">✎</button>
                  <button type="button" onClick={() => removeCustomPreset(preset)}
                    aria-label={`Delete custom preset ${preset.name}`} title="Delete preset"
                    className="grid h-5 w-5 place-items-center rounded text-[0.625rem] text-content-subtle hover:bg-red-500/15 hover:text-red-300">✕</button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Shot list header + card-state legend — three unambiguous states (the
          amber chips in the group headers are the composition quota, a
          separate concern). */}
      <div className="flex items-center gap-2 pt-1">
        <span className="text-content-muted text-[0.6875rem] uppercase">Shots</span>
        <span className="text-content-subtle text-[0.625rem]">
          {(recommendedIds?.length || 0) > 0
            ? 'the coverage plan pre-selected missing combinations — click any card to add or remove it'
            : 'a preset pre-selects a balanced mix — click any card to add or remove it'}
        </span>
      </div>
      {settingsError && (
        <p role="alert" className="m-0 rounded border border-amber-400/40 bg-amber-500/10 px-2 py-1.5 text-xs text-amber-200">
          Engine settings could not be loaded. Generation is disabled; reopen this panel to retry.
        </p>
      )}
      <div className="flex items-center gap-3 flex-wrap text-[0.625rem] text-content-subtle" aria-hidden="true">
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 rounded border border-primary/50 bg-primary/20 ring-1 ring-primary/30" />
          selected — will be generated
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 rounded border border-emerald-500/40 bg-emerald-500/10" />
          <span className="text-emerald-300">✓×N</span> already in your dataset
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 rounded border border-border bg-app/40" />
          not selected
        </span>
      </div>

      {/* Shot picker, grouped by framing with a quota progress bar per group. */}
      <div className="max-h-80 overflow-auto flex flex-col gap-2 pr-1">
        {FRAMING_ORDER.map((fr) => {
          const have = (composition && composition[fr]) || 0;
          const target = Number(coverageTargets?.[fr] ?? TARGET[fr]);
          const missing = Math.max(0, target - have);
          const pct = Math.min(100, (have / Math.max(1, target)) * 100);
          const selCount = byFraming[fr].filter((e) => selected.has(e.id)).length;
          return (
            <div key={fr}>
              <div className="flex items-center gap-2 mb-1"
                title={`Your dataset contains ${have} "${FRAMING_LABEL[fr]}" image(s). This dataset's coverage target is ${target} (this quota does NOT affect the generation selection).`}>
                <ShotIllustration framing={fr} label=""
                  className={`w-5 h-5 ${missing ? 'text-amber-300' : 'text-content-subtle'}`} />
                <span className={`text-[0.6875rem] uppercase font-semibold ${missing ? 'text-amber-300' : 'text-content-muted'}`}>
                  {FRAMING_LABEL[fr]}
                </span>
                <span className="w-24 h-1.5 rounded-full bg-app/60 overflow-hidden" aria-hidden="true">
                  <span className={`block h-full rounded-full ${missing ? 'bg-amber-400' : 'bg-emerald-400'}`}
                    style={{ width: `${pct}%` }} />
                </span>
                {missing > 0 ? (
                  <span className="px-1.5 py-px rounded-full bg-amber-400/15 border border-amber-400/40 text-amber-300 text-[0.625rem]">
                    {have}/{target} in the dataset · {missing} missing
                  </span>
                ) : (
                  <span className="text-emerald-400/90 text-[0.625rem]">✓ {have}/{target}</span>
                )}
                {selCount > 0 && (
                  <span className="ml-auto text-content-subtle text-[0.625rem]">{selCount} selected</span>
                )}
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-1.5">
                {byFraming[fr].map((e) => {
                  const on = selected.has(e.id);
                  const done = doneByLabel.get(e.label) || 0;
                  const emoji = contextEmoji(e.label);
                  // Three unambiguous states (cf. legend above): indigo = selected,
                  // green = already generated in this dataset, neutral = neither.
                  // The old amber "deficit" glow on unselected cards read as a
                  // selection — the quota cue now lives only in the group header.
                  const cls = on
                    ? 'bg-primary/20 border-primary/50 text-white ring-1 ring-primary/30'
                    : done > 0
                      ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-100/90 hover:bg-emerald-500/15'
                      : 'border-border bg-app/40 text-content-muted hover:bg-surface-raised';
                  return (
                    <button key={e.id} type="button" onClick={() => toggle(e.id)}
                      aria-pressed={on}
                      title={done > 0 ? `${done} image(s) of this shot already in the dataset` : undefined}
                      className={`flex items-center gap-1.5 px-1.5 py-1 rounded-lg text-[0.625rem] border text-left transition-colors ${cls}`}>
                      <ShotIllustration framing={e.framing} label={e.label} className="w-7 h-7 shrink-0" />
                      <span className="min-w-0 leading-tight">
                        {emoji && <span className="mr-1" aria-hidden="true">{emoji}</span>}
                        {displayLabel(e.label)}
                      </span>
                      <span className="ml-auto shrink-0 flex items-center gap-1">
                        {done > 0 && (
                          <span className="text-emerald-300 font-semibold" aria-label={`${done} already in the dataset`}>
                            ✓×{done}
                          </span>
                        )}
                        {on && <span className="text-indigo-300" aria-hidden="true">✓</span>}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}

        {/* Custom group — user-authored cards (the only deletable ones). */}
        {customShots.length > 0 && (
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span aria-hidden="true">✨</span>
              <span className="text-[0.6875rem] uppercase font-semibold text-content-muted">Custom</span>
              <span className="text-content-subtle text-[0.625rem]">your own shots — remove with ✕</span>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-1.5">
              {customShots.map((c) => {
                const on = selected.has(c.id);
                const done = doneByLabel.get(c.label) || 0;
                const blocked = c.nsfw && !isKlein;   // 🔞 card while an API engine is active
                const cls = on
                  ? 'bg-primary/20 border-primary/50 text-white ring-1 ring-primary/30'
                  : done > 0
                    ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-100/90 hover:bg-emerald-500/15'
                    : 'border-border bg-app/40 text-content-muted hover:bg-surface-raised';
                return (
                  <div key={c.id} className={`relative flex items-center gap-1.5 px-1.5 py-1 rounded-lg text-[0.625rem] border transition-colors ${cls} ${blocked ? 'opacity-40' : ''}`}>
                    <button type="button" onClick={() => !blocked && toggle(c.id)} aria-pressed={on}
                      disabled={blocked}
                      title={blocked ? '🔞 shot — switch the generator to Klein' : c.prompt}
                      className="flex items-center gap-1.5 flex-1 min-w-0 text-left disabled:cursor-not-allowed">
                      <ShotIllustration framing={c.framing} label={c.label} className="w-7 h-7 shrink-0" />
                      <span className="min-w-0 leading-tight truncate">{c.label}</span>
                      <span className="ml-auto shrink-0 flex items-center gap-1">
                        {done > 0 && <span className="text-emerald-300 font-semibold">✓×{done}</span>}
                        {on && <span className="text-indigo-300" aria-hidden="true">✓</span>}
                      </span>
                    </button>
                    <button type="button" onClick={() => removeCustomShot(c.id)}
                      aria-label={`Remove custom shot ${c.label}`} title="Remove this custom shot"
                      className="shrink-0 w-4 h-4 grid place-items-center rounded bg-black/40 text-content-subtle hover:text-white text-[0.625rem] leading-none">
                      ✕
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* 🔞 NSFW — local Klein only. Uncensored body catalog + free prompt.
          Never offered on the API engines (and the backend refuses them there). */}
      {isKlein && klAvailable && (
        <div className={`rounded-lg border p-2 flex flex-col gap-2 ${nsfwMode
          ? 'border-rose-500/40 bg-rose-500/5' : 'border-border bg-app/30'}`}>
          <button type="button" onClick={() => setNsfwMode((v) => !v)} aria-pressed={nsfwMode}
            className="flex items-center gap-2 text-left">
            <span aria-hidden="true">🔞</span>
            <span className={`text-[0.75rem] font-semibold ${nsfwMode ? 'text-rose-300' : 'text-content-muted'}`}>
              NSFW mode {nsfwMode ? 'ON' : 'OFF'}
            </span>
            <span className="text-content-subtle text-[0.625rem]">
              uncensored body shots — generated locally by Klein, never sent to an API
            </span>
            <span className={`ml-auto w-8 h-4 rounded-full relative transition-colors ${nsfwMode ? 'bg-rose-500/70' : 'bg-app/80 border border-border'}`}
              aria-hidden="true">
              <span className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all ${nsfwMode ? 'left-4' : 'left-0.5'}`} />
            </span>
          </button>
          {nsfwMode && (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-1.5">
                {nsfwCatalog.map((e) => {
                  const on = selected.has(e.id);
                  const done = doneByLabel.get(e.label) || 0;
                  const cls = on
                    ? 'bg-rose-500/20 border-rose-400/60 text-white ring-1 ring-rose-400/30'
                    : done > 0
                      ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-100/90 hover:bg-emerald-500/15'
                      : 'border-border bg-app/40 text-content-muted hover:bg-surface-raised';
                  return (
                    <button key={e.id} type="button" onClick={() => toggle(e.id)} aria-pressed={on}
                      title={done > 0 ? `${done} image(s) of this shot already in the dataset` : e.prompt}
                      className={`flex items-center gap-1.5 px-1.5 py-1 rounded-lg text-[0.625rem] border text-left transition-colors ${cls}`}>
                      <ShotIllustration framing={e.framing} label={e.label} className="w-7 h-7 shrink-0" />
                      <span className="min-w-0 leading-tight">{displayLabel(e.label)}</span>
                      <span className="ml-auto shrink-0 flex items-center gap-1">
                        {done > 0 && <span className="text-emerald-300 font-semibold">✓×{done}</span>}
                        {on && <span className="text-rose-300" aria-hidden="true">✓</span>}
                      </span>
                    </button>
                  );
                })}
              </div>
              <p className="text-content-subtle text-[0.625rem]">
                Captions must keep describing the state (nude / lingerie…) so it stays
                promptable and does not bind to the trigger word — the captioner does this
                automatically. The Custom shot below follows this register while 🔞 is on.
              </p>
            </>
          )}
        </div>
      )}

      {/* Custom shot — free prompt, EVERY engine (rides the 🔞 register only when
          NSFW mode is on with Klein). Included in the next Generate alongside the
          selected catalog shots. Collapsed by default (power-user tool) — the
          <details> keeps its fields mounted, so drafts survive fold/unfold. */}
      <details className="rounded-lg border border-border bg-app/30 open:pb-2">
        <summary className="cursor-pointer select-none px-2.5 py-1.5 text-[0.75rem] text-content font-semibold">
          ✨ Custom shot
          <span className="ml-2 font-normal text-content-subtle text-[0.625rem]">
            write your own prompt — it becomes a reusable card in the Custom group above{nsfwMode && isKlein ? ' — 🔞 register active' : ''}
          </span>
        </summary>
        <div className="px-2.5 pt-1 flex flex-col gap-1">
          <label className="text-content-muted text-[0.6875rem]" htmlFor="custom-shot-prompt">
            Describe outfit, pose and setting, pick a framing, then Add.
          </label>
          <div className="flex gap-1.5 items-start">
            <textarea id="custom-shot-prompt" value={customPrompt} rows={2}
              onChange={(e) => setCustomPrompt(e.target.value)}
              placeholder="e.g. full body shot, sitting on a vintage motorbike in a garage, leather jacket, warm light"
              className="flex-1 bg-app/60 border border-border rounded px-2 py-1 text-[0.6875rem] text-content resize-y" />
            <select value={customFraming} onChange={(e) => setCustomFraming(e.target.value)}
              aria-label="Custom shot framing"
              className="bg-app/60 border border-border rounded px-1 py-1 text-[0.6875rem] text-content">
              {FRAMING_ORDER.map((fr) => (
                <option key={fr} value={fr}>{FRAMING_LABEL[fr]}</option>
              ))}
            </select>
            <button type="button" onClick={addCustomShot} disabled={!customPrompt.trim()}
              className="px-2.5 py-1 rounded-lg bg-gradient-primary text-white text-[0.6875rem] font-semibold disabled:opacity-40">
              ＋ Add
            </button>
          </div>
        </div>
      </details>

      {/* Klein-only tuning, grouped: model file + consistency-LoRA strength.
          A <details> so the defaults stay out of a newcomer's way — children
          remain mounted, so the model picker still reports its choice. */}
      {isKlein && klAvailable && (
        <details className="rounded-lg border border-border bg-app/30 open:pb-2">
          <summary className="cursor-pointer select-none px-2.5 py-1.5 text-[0.75rem] text-content font-semibold">
            🖥️ Klein tuning
            <span className="ml-2 font-normal text-content-subtle text-[0.625rem]">
              model file · consistency LoRA {loraStrength <= 0 ? 'off' : loraStrength.toFixed(2)}
            </span>
          </summary>
          <div className="px-2.5 pt-1 flex flex-col gap-2">
            <div className="max-w-sm"><Flux2KleinModelPicker onChange={setKlein} /></div>
            <div className="flex flex-col gap-0.5">
              <label className="flex items-center gap-2 text-content-muted text-[0.6875rem]">
                <span className="whitespace-nowrap">
                  Consistency LoRA: {loraStrength <= 0 ? 'off' : loraStrength.toFixed(2)}
                </span>
                <input type="range" min={0} max={1.2} step={0.05} value={loraStrength}
                  onChange={(e) => setLoraStrength(Number(e.target.value))}
                  aria-label="Consistency LoRA strength"
                  className="flex-1 min-w-[120px] accent-indigo-500" />
              </label>
              <p className="text-content-subtle text-[0.625rem]">
                Anchors the COMPOSITION, not the face — high values suppress pose/framing changes.
                ~0.5 balanced · 0.2–0.4 for big restagings · 0 = off. Face identity comes from the
                reference photo(s); add extra references for a stronger identity lock.
              </p>
            </div>
          </div>
        </details>
      )}
      <div className="flex items-center gap-2 flex-wrap border-t border-border pt-2">
        <span className="text-content-muted text-[0.6875rem]">{selected.size} selected</span>
        {selected.size > 0 && (
          <button type="button" onClick={() => setSelected(new Set())}
            className="text-content-subtle text-[0.6875rem] underline decoration-border hover:text-content"
            title="Clear the whole selection (presets and shots)">
            ✕ Deselect all
          </button>
        )}
        <label className="text-content-muted text-[0.6875rem] flex items-center"
          title="Generate each selected shot this many times">×
          <select value={multiplier} onChange={(e) => setMultiplier(+e.target.value)}
            aria-label="Variation multiplier"
            className="bg-app/60 border border-border rounded px-1 py-0.5 text-content ml-1">
            {[1, 2, 3].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        {!hasRef && (
          <span className="text-amber-300 text-[0.6875rem]">Import photos or set a reference first</span>
        )}
        {hasRef && isKlein && !hasPrimaryRef && (
          <span className="text-amber-300 text-[0.6875rem]">Klein needs a primary reference; use an API engine for the imported pool</span>
        )}
        {/* Disabled for the WHOLE batch, not just the launch request: `busy` is the
            hook's busyLive (local flag OR any server-side activity, restored on
            reload), so a generation already in flight — Nano Banana / ChatGPT /
            Klein alike — keeps this locked with a visible reason. */}
        <button type="button" onClick={go}
          disabled={busy || !selected.size || !hasRef || !currentAvailable || (isKlein && !hasPrimaryRef)}
          title={generating ? 'A generation batch is already running' : undefined}
          className="ml-auto px-4 py-1.5 rounded-lg bg-gradient-primary text-white text-sm font-semibold disabled:opacity-40">
          {busy
            ? (generating
                ? `Generating…${generating.total ? ` ${generating.done}/${generating.total}` : ''}`
                : '…')
            : `⚡ Generate (${selected.size * multiplier})`}
        </button>
      </div>
    </div>
  );
}
