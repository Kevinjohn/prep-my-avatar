import TrainingPresetControls from './TrainingPresetControls'
import { CUSTOM_BASE_SENTINEL } from './trainingPanelModel'

/** Advanced recipe, base, masking, queue, and scheduling controls. */
export default function TrainingAdvancedOptions(props) {
  const {
    LR_SCHED_LABELS, adv, advAlphaChoice, advAlphaChoices, advDefaultAlpha, advDefaultRank,
    advDropout, advDropoutChoices, advEffAlpha, advEffRank, advEma, advEmaChoices,
    advGradAccum, advGradAccumChoices, advLrSched, advLrSchedChoices, advMaxPrompts, advNetworkChoices,
    advNetworkSupported, advNetworkType, advOptimizer, advOptimizerChoices, advRankChoice, advRes,
    advSampleDefault, advSampleEvery, advSampleEveryChoices, advSave, advTimestep, advTimestepChoices,
    advTimestepDefault, advTimestepSupported, advWarmup, advWarmupChoices, advancedOpen, base,
    baseBlocksTrain, baseConverted, baseInfo, baseLabel, comfyConfigured, concept,
    convertError, convertRunning, currentBases, customBase, customSupported, doPrepareBase,
    hasInvalidStepsOverride, isCustomBase, keptCount, launchConfigReady, masked, maskedRembgMissing,
    needsConversion, openSched, preflightFloor, presetController, queued, recoSteps,
    samplePromptsText, saveAdv, saveSamplePrompts, schedAt, schedule, setAdvancedOpen,
    setBase, setCustomBase, setMasked, setSamplePromptsText, setSchedAt, setStepsOverride,
    setTePath, setVaePath, setVariant, showSched, status, stepsInfo, stepsOverride,
    stepsOverrideValid, tePath, togglePanel, trainType, typeLabel, vaePath,
    vaeTeSupported, variant,
  } = props
  return (
    <details id="ds-training-advanced" open={advancedOpen}
      className="rounded-lg border border-border bg-surface open:pb-2.5 scroll-mt-20">
      <summary data-workspace-focus
        onClick={togglePanel('advanced', advancedOpen, setAdvancedOpen)}
        className="cursor-pointer select-none px-3 py-2 text-sm text-content font-semibold">
        ⚙️ Advanced options
        <span className="ml-2 font-normal text-content-subtle text-[0.6875rem]">
          base &amp; variant · rank · resolution · masked · steps · scheduling · presets
        </span>
      </summary>
      <div className="px-3 pt-1 flex flex-col gap-2">
        {/* --- Presets : réglages nommés, ré-applicables et partageables en JSON.
             Appliquer REMPLACE les réglages explicites du dataset ; les clés
             inconnues d'un fichier importé sont ignorées (tolérance de version). --- */}
        <TrainingPresetControls controller={presetController} />
        {/* --- Base d'entraînement : officielle (recommandé) ou merge ComfyUI custom.
             Affichée MÊME pendant un training en cours → choisir la base du job mis
             en file (sinon « Mettre en file » réutilisait silencieusement la base persistée). --- */}
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-content-muted text-[0.625rem] uppercase">
              Base{status.in_progress ? ' (next queued job)' : ''}
            </span>
            <select value={customBase ? CUSTOM_BASE_SENTINEL : base}
              onChange={(e) => {
                const v = e.target.value;
                if (v === CUSTOM_BASE_SENTINEL) { setCustomBase(true); setBase(''); }
                else { setCustomBase(false); setBase(v); }
              }}
              aria-label="Base model"
              className="px-2 py-1 rounded-lg border border-border bg-surface text-content text-[0.75rem] max-w-[230px]">
              {(currentBases.length ? currentBases
                : [{ value: '', label: trainType === 'sdxl' ? (comfyConfigured ? 'No SDXL checkpoint found' : 'ComfyUI not configured') : trainType === 'krea' ? 'Official — Krea 2' : trainType === 'flux' ? 'Official — FLUX.1-dev' : trainType === 'flux2klein' ? 'Official — FLUX.2 Klein' : 'Official — Z-Image-Turbo' }]).map((b) => (
                <option key={b.value} value={b.value}>
                  {b.label}{b.value && baseInfo?.converted?.[b.value] ? ' ✓' : ''}
                </option>
              ))}
              {/* Local-only: a free path to a .safetensors of the SAME architecture. */}
              {customSupported && (
                <option value={CUSTOM_BASE_SENTINEL}>Custom weights… (local file)</option>
              )}
            </select>
            {trainType === 'zimage' && isCustomBase && (
              <select value={variant} onChange={(e) => setVariant(e.target.value)}
                title="Base model variant (sets the de-distillation adapter + the sampler)"
                className="px-2 py-1 rounded-lg border border-border bg-surface text-content text-[0.75rem]">
                <option value="turbo">Turbo (distilled)</option>
                <option value="base">Base (non-distilled)</option>
                <option value="deturbo">De-Turbo</option>
              </select>
            )}
            {/* Krea 2 : reco officielle « train on Raw, validate on Turbo ». Le RAW
                (non distillé) est le checkpoint prévu pour le fine-tuning ; sa LoRA
                transfère vers Turbo à l'inférence. Turbo+adapter = alternative VRAM. */}
            {trainType === 'krea' && (
              <select value={variant} onChange={(e) => setVariant(e.target.value)}
                aria-label="Krea 2 training base"
                title="Krea 2 training base — Raw is the official recommendation (best quality; the LoRA transfers to Turbo at inference). Turbo+adapter is the VRAM-friendly alternative. First Raw training downloads the Raw weights (~24 GB) and runs longer."
                className="px-2 py-1 rounded-lg border border-border bg-surface text-content text-[0.75rem]">
                <option value="base">Raw (recommended)</option>
                <option value="turbo">Turbo (w/ adapter)</option>
              </select>
            )}
            {/* FLUX.2 Klein : deux TAILLES de base (pas une histoire de distillation
                comme Krea) — 4B = la voie locale 16-24 GB, 9B = 32-48 GB, pensé
                pour ☁️ Train in cloud. Les deux sont gated sur Hugging Face. */}
            {trainType === 'flux2klein' && (
              <select value={variant} onChange={(e) => setVariant(e.target.value)}
                aria-label="FLUX.2 Klein model size"
                title="FLUX.2 Klein model size — 4B fits a 16-24 GB local GPU (recommended locally); 9B needs 32-48 GB VRAM, best trained via ☁️ Train in cloud. Both bases are gated on Hugging Face: accept the license and set a HF token before the first run."
                className="px-2 py-1 rounded-lg border border-border bg-surface text-content text-[0.75rem]">
                <option value="4b">4B (local, 16-24 GB)</option>
                <option value="9b">9B (cloud, 32-48 GB)</option>
              </select>
            )}
          </div>
          {/* « Custom weights… » : chemin local vers un .safetensors de la MÊME
              architecture. Local-only (le cloud refuse), TE/VAE restent officiels
              (sauf les overrides SDXL séparés plus bas). Vérifié au lancement. */}
          {customBase && customSupported && (
            <div className="flex flex-col gap-1">
              <input type="text" value={base} onChange={(e) => setBase(e.target.value)}
                spellCheck={false}
                placeholder={trainType === 'sdxl'
                  ? 'C:\\path\\to\\your-sdxl-checkpoint.safetensors'
                  : `C:\\path\\to\\your-${typeLabel.toLowerCase().replace(/[^a-z0-9]+/g, '')}-model.safetensors`}
                aria-label="Custom weights path"
                className="px-2 py-1 rounded-lg border border-border bg-surface text-content text-[0.75rem] font-mono w-full max-w-[520px]" />
              <span className="text-content-subtle text-[0.625rem] leading-relaxed">
                Local path to a <b className="text-content-muted font-medium">{typeLabel}</b> .safetensors
                (same architecture). The file is checked at launch (exists, valid, arch signature);
                an unrecognized file asks for confirmation. Local-only — cloud training refuses it.
              </span>
            </div>
          )}
          {/* krea et flux2klein n'ont QUE des bases officielles fixes (rien à
              lister depuis ComfyUI) → le warning « bases can't be listed » n'y
              apporte que du bruit. */}
          {!comfyConfigured && trainType !== 'krea' && trainType !== 'flux2klein' && (
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-amber-300 text-[0.625rem]">
                ⚠️ ComfyUI folder not set — training bases can't be listed{trainType === 'sdxl' ? '' : ' (the official Z-Image base still works)'}.
              </span>
              <a href="#/setup"
                className="px-2.5 py-1 rounded-lg bg-indigo-500/20 border border-indigo-400/40 text-indigo-200 text-[0.6875rem] font-semibold">
                Point the app at ComfyUI →
              </a>
            </div>
          )}
          {needsConversion && !baseConverted && !convertRunning && (
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-amber-300 text-[0.625rem]">⚠️ Base must be converted before training (~12 GB, a few min, one time only).</span>
              <button type="button" onClick={doPrepareBase}
                className="px-2.5 py-1 rounded-lg bg-indigo-500/20 border border-indigo-400/40 text-indigo-200 text-[0.6875rem] font-semibold">
                ⚙️ Convert the base
              </button>
            </div>
          )}
          {convertRunning && (
            <span className="text-indigo-300 text-[0.625rem] flex items-center gap-1.5">
              <span className="inline-block w-3 h-3 border-2 border-indigo-400/40 border-t-indigo-400 rounded-full animate-spin" aria-hidden />
              Converting the base… (~a few minutes)
            </span>
          )}
          {baseConverted && (
            <span className="text-green-400/80 text-[0.625rem]">✓ Base ready — training will produce a LoRA native to this model.</span>
          )}
          {convertError && (
            <span className="text-red-300 text-[0.625rem] break-words">❌ Conversion failed: {convertError}</span>
          )}
          {/* SDXL-only: separate VAE / text-encoder overrides. SDXL is the one
              family where ai-toolkit honours these top-level (every other family
              bundles its TE/VAE) — the server refuses them elsewhere. Optional. */}
          {vaeTeSupported && (
            <div className="flex flex-col gap-1.5 mt-1 pt-2 border-t border-white/[0.07]">
              <span className="text-content-muted text-[0.625rem] uppercase">
                SDXL overrides (optional)
              </span>
              <label className="flex flex-col gap-0.5">
                <span className="text-content text-[0.6875rem]">VAE path</span>
                <input type="text" value={vaePath} onChange={(e) => setVaePath(e.target.value)}
                  spellCheck={false} placeholder="leave empty to use the checkpoint's own VAE"
                  aria-label="SDXL VAE path"
                  className="px-2 py-1 rounded-lg border border-border bg-surface text-content text-[0.75rem] font-mono w-full max-w-[520px]" />
              </label>
              <label className="flex flex-col gap-0.5">
                <span className="text-content text-[0.6875rem]">Text encoder path or repo</span>
                <input type="text" value={tePath} onChange={(e) => setTePath(e.target.value)}
                  spellCheck={false} placeholder="leave empty to use the checkpoint's own text encoders"
                  aria-label="SDXL text encoder path or HF repo"
                  className="px-2 py-1 rounded-lg border border-border bg-surface text-content text-[0.75rem] font-mono w-full max-w-[520px]" />
              </label>
              <span className="text-content-subtle text-[0.625rem] leading-relaxed">
                Leave both empty to use the checkpoint's own VAE/text encoders. A VAE is a local
                .safetensors; the text encoder may be a local folder or a Hugging Face repo id.
                Checked at launch. These are SDXL-only and local-only (cloud training refuses them).
              </span>
            </div>
          )}
        </div>

        {/* Model & training knobs — researched defaults (see the Research note),
            editable per dataset. Each carries a plain-English "why / how". */}
        <div className="flex flex-col rounded-lg border border-border bg-app/30 p-2.5 divide-y divide-white/[0.07] [&>*]:py-2.5 [&>*:first-child]:pt-0 [&>*:last-child]:pb-0">
          <div className="flex items-center gap-1.5 text-indigo-300/80 text-[0.625rem] font-semibold uppercase tracking-wider">
            <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-indigo-400/60" /> Model &amp; training
          </div>

          <div className="flex flex-col gap-0.5">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-content text-[0.75rem] w-28 shrink-0">LoRA rank</span>
              <select value={String(advRankChoice)}
                onChange={(e) => saveAdv({ rank: e.target.value === 'auto' ? 'auto' : Number(e.target.value) })}
                aria-label="LoRA rank"
                className="px-2 py-1 rounded-lg border border-border bg-surface text-content text-[0.75rem]">
                <option value="auto">Auto ({advDefaultRank})</option>
                <option value="8">8</option><option value="16">16</option><option value="24">24</option>
                <option value="32">32</option><option value="48">48</option><option value="64">64</option>
              </select>
              <span className="text-content-subtle text-[0.625rem] tabular-nums">→ rank {advEffRank} / alpha {advEffAlpha}</span>
            </div>
            <span className="text-content-subtle text-[0.6875rem] leading-relaxed">
              <b className="text-content-muted font-medium">Why:</b> how much capacity the LoRA has to memorize the
              identity. <b className="text-content-muted font-medium">How:</b> higher (32+) captures a hard face more
              faithfully but makes a bigger file and can overfit small sets; lower (16) is lighter and fine for clean
              frontal datasets. ai-toolkit ties alpha to rank (SDXL keeps alpha = rank ÷ 2).
            </span>
          </div>

          <div className="flex flex-col gap-0.5">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-content text-[0.75rem] w-28 shrink-0">Resolution</span>
              <select value={advRes} onChange={(e) => saveAdv({ resolution: e.target.value })}
                aria-label="Training resolution"
                className="px-2 py-1 rounded-lg border border-border bg-surface text-content text-[0.75rem]">
                <option value="768,1024">768 + 1024 (multi-scale)</option>
                <option value="1024">1024 only</option>
                <option value="768">768 only (low VRAM)</option>
              </select>
            </div>
            <span className="text-content-subtle text-[0.6875rem] leading-relaxed">
              <b className="text-content-muted font-medium">Why:</b> the size(s) images are trained at — and the #1
              VRAM lever. <b className="text-content-muted font-medium">How:</b> multi-scale trains at two sizes so
              the LoRA holds up from a close-up face to a full-body shot; single 1024 is a bit faster.
              <b className="text-content-muted font-medium"> 768 only</b> cuts memory use sharply and trains much
              faster — your best shot at Krea 2 on a GPU under 24 GB, at some cost in fine detail.
            </span>
          </div>

          <div className="flex flex-col gap-0.5">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-content text-[0.75rem] w-28 shrink-0">Save checkpoint</span>
              <select value={String(advSave)} onChange={(e) => saveAdv({ save_every: Number(e.target.value) })}
                aria-label="Checkpoint frequency"
                className="px-2 py-1 rounded-lg border border-border bg-surface text-content text-[0.75rem]">
                <option value="250">every 250 steps</option>
                <option value="500">every 500 steps</option>
                <option value="1000">every 1000 steps</option>
              </select>
            </div>
            <span className="text-content-subtle text-[0.6875rem] leading-relaxed">
              <b className="text-content-muted font-medium">Why:</b> how often a checkpoint is written.
              <b className="text-content-muted font-medium"> How:</b> finer (250) gives more epochs to pick the
              least-overfit one in the Test Studio; coarser saves disk.
            </span>
          </div>

          <div className="flex flex-col gap-0.5">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-content text-[0.75rem] w-28 shrink-0">Saves kept</span>
              <select value={String(adv?.max_step_saves ?? 4)}
                onChange={(e) => saveAdv({ max_step_saves: Number(e.target.value) })}
                aria-label="Maximum intermediate saves kept"
                className="px-2 py-1 rounded-lg border border-border bg-surface text-content text-[0.75rem]">
                <option value="2">last 2</option>
                <option value="3">last 3</option>
                <option value="4">last 4</option>
                <option value="6">last 6</option>
                <option value="10">last 10</option>
              </select>
            </div>
            <span className="text-content-subtle text-[0.6875rem] leading-relaxed">
              <b className="text-content-muted font-medium">Why:</b> older intermediate saves are deleted by
              ai-toolkit itself (local and cloud) past this count — the old default of 10 piled up ~10 GB per
              Krea run. <b className="text-content-muted font-medium">How:</b> 4 is plenty to pick the best
              epoch; raise it only for long runs you want to comb through finely.
            </span>
          </div>

          <div className="flex flex-col gap-0.5">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-content text-[0.75rem] w-28 shrink-0">Preview every</span>
              <select value={String(advSampleEvery)} onChange={(e) => saveAdv({ sample_every: Number(e.target.value) })}
                aria-label="Preview sample frequency"
                className="px-2 py-1 rounded-lg border border-border bg-surface text-content text-[0.75rem]">
                {advSampleEveryChoices.map((n) => (
                  <option key={n} value={String(n)}>every {n} steps</option>
                ))}
              </select>
            </div>
            <label className="flex flex-col gap-1 mt-1">
              <span className="text-content text-[0.75rem]">Preview prompts</span>
              <textarea value={samplePromptsText}
                onChange={(e) => setSamplePromptsText(e.target.value)}
                onBlur={saveSamplePrompts}
                rows={4}
                placeholder={advSampleDefault.length ? advSampleDefault.join('\n') : 'one prompt per line'}
                aria-label="Preview sample prompts, one per line"
                className="px-2 py-1.5 rounded-lg border border-border bg-surface text-content text-[0.75rem] font-mono leading-relaxed resize-y placeholder:text-content-subtle" />
            </label>
            <span className="text-content-subtle text-[0.6875rem] leading-relaxed">
              <b className="text-content-muted font-medium">Why:</b> these are the test images ai-toolkit renders
              during the run so you can watch the LoRA learn (and later pick the best epoch).
              <b className="text-content-muted font-medium"> How:</b> one prompt per line, up to {advMaxPrompts}. Your
              trigger word is added automatically if you leave it out. {concept
                ? 'Leave empty for concept-friendly defaults (the greyed text) — the portrait wording only fits a person LoRA.'
                : 'Leave empty for the portrait defaults shown greyed.'}
            </span>
          </div>
        </div>

        {/* Expert — last-mile levers. Collapsed by default; every control defaults
            to the current behaviour, so a newcomer who never opens this is unaffected. */}
        <details className="group rounded-lg border border-indigo-400/40 border-l-[3px] border-l-indigo-400 bg-indigo-500/[0.14] transition-colors hover:bg-indigo-500/20">
          <summary className="flex items-center gap-2 cursor-pointer select-none list-none [&::-webkit-details-marker]:hidden px-2.5 py-2.5 text-[0.6875rem] font-semibold uppercase tracking-wider text-indigo-100 hover:text-white">
            <span aria-hidden className="text-indigo-300 transition-transform group-open:rotate-90">▸</span>
            <span aria-hidden>🔬</span>
            <span>Expert — last-mile levers</span>
            <span className="ml-auto hidden sm:inline normal-case font-normal tracking-normal text-indigo-300/50">network · alpha · dropout{advTimestepSupported ? ' · timestep' : ''} · optimizer · schedule · EMA</span>
          </summary>
          <div className="flex flex-col px-2.5 pb-2.5 divide-y divide-indigo-400/10 [&>div]:py-2.5 [&>div:first-child]:pt-1 [&>div:last-child]:pb-0">
            {/* Network variant — LoRA (default) or LoKr. LoKr is arch-generic in
                ai-toolkit, so it's offered on every family; the *_supported guard
                mirrors the timestep pattern for a future family that can't run it. */}
            <div className="flex flex-col gap-0.5">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-content text-[0.75rem] w-28 shrink-0">Network</span>
                <select value={advNetworkType} onChange={(e) => saveAdv({ network_type: e.target.value })}
                  aria-label="Network type"
                  className="px-2 py-1 rounded-lg border border-border bg-surface text-content text-[0.75rem]">
                  {advNetworkChoices.map((n) => <option key={n} value={n}>{n === 'lora' ? 'LoRA (default)' : 'LoKr'}</option>)}
                </select>
                {advNetworkType === 'lokr' && !advNetworkSupported && (
                  <span className="text-amber-300 text-[0.625rem]" title={`LoKr isn't supported for ${trainType} — this run would fall back to LoRA.`}>⚠ not supported for {trainType}</span>
                )}
              </div>
              <span className="text-content-subtle text-[0.6875rem] leading-relaxed">
                <b className="text-content-muted font-medium">Why:</b> LoKr often locks likeness earlier at small
                rank — community recipe: LoKr + low rank + EMA. <b className="text-content-muted font-medium">How:</b> LoRA
                (default) is the standard adapter; LoKr factorises the update differently and can capture identity in
                fewer steps on a tiny set. Pair it with a low rank and EMA below.
              </span>
            </div>
            {/* EMA — exponential moving average of the weights */}
            <div className="flex flex-col gap-0.5">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-content text-[0.75rem] w-28 shrink-0">EMA</span>
                <select value={String(advEma)}
                  onChange={(e) => saveAdv({ ema: e.target.value === '0' ? 'off' : Number(e.target.value) })}
                  aria-label="EMA (exponential moving average)"
                  className="px-2 py-1 rounded-lg border border-border bg-surface text-content text-[0.75rem]">
                  <option value="0">Off (default)</option>
                  {advEmaChoices.map((d) => <option key={d} value={String(d)}>{d}</option>)}
                </select>
              </div>
              <span className="text-content-subtle text-[0.6875rem] leading-relaxed">
                <b className="text-content-muted font-medium">Why:</b> exponential moving average of the weights —
                smoother, often better checkpoints. <b className="text-content-muted font-medium">How:</b> Off by
                default; 0.99 averages faster (the recommended pairing with LoKr on small sets), 0.999 is slower and
                steadier.
              </span>
            </div>
            {/* Decoupled alpha */}
            <div className="flex flex-col gap-0.5">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-content text-[0.75rem] w-28 shrink-0">Alpha</span>
                <select value={String(advAlphaChoice)}
                  onChange={(e) => saveAdv({ alpha: e.target.value === 'auto' ? 'auto' : Number(e.target.value) })}
                  aria-label="LoRA alpha"
                  className="px-2 py-1 rounded-lg border border-border bg-surface text-content text-[0.75rem]">
                  <option value="auto">Auto (= {advDefaultAlpha})</option>
                  {advAlphaChoices.map((a) => <option key={a} value={String(a)}>{a}</option>)}
                </select>
                <span className="text-content-subtle text-[0.625rem] tabular-nums">→ scale {(advEffAlpha / Math.max(1, advEffRank)).toFixed(2)}×</span>
              </div>
              <span className="text-content-subtle text-[0.6875rem] leading-relaxed">
                <b className="text-content-muted font-medium">Why:</b> alpha ÷ rank is the LoRA&apos;s effective strength while
                training — a soft learning-rate lever that isn&apos;t the LR. <b className="text-content-muted font-medium">How:</b> Auto
                ties alpha to rank (scale 1.0); a lower alpha (e.g. ½ rank) softens the fit — a clean way to stop a tiny
                (≤20-image) set from memorising without touching LR or rank.
              </span>
            </div>
            {/* Network dropout */}
            <div className="flex flex-col gap-0.5">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-content text-[0.75rem] w-28 shrink-0">Network dropout</span>
                <select value={String(advDropout)}
                  onChange={(e) => saveAdv({ dropout: e.target.value === '0' ? 'off' : Number(e.target.value) })}
                  aria-label="Network dropout"
                  className="px-2 py-1 rounded-lg border border-border bg-surface text-content text-[0.75rem]">
                  <option value="0">Off</option>
                  {advDropoutChoices.map((d) => <option key={d} value={String(d)}>{d}</option>)}
                </select>
              </div>
              <span className="text-content-subtle text-[0.6875rem] leading-relaxed">
                <b className="text-content-muted font-medium">Why:</b> the anti-overfit regulariser for small sets — randomly
                drops LoRA weights so it generalises instead of memorising. <b className="text-content-muted font-medium">How:</b> Off
                by default; 0.05–0.1 is a gentle start for a tiny (≤20-image) dataset, higher = stronger regularisation.
              </span>
            </div>
            {/* Timestep weighting — flowmatch families only (SDXL disables it) */}
            {advTimestepSupported && (
              <div className="flex flex-col gap-0.5">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-content text-[0.75rem] w-28 shrink-0">Timestep weighting</span>
                  <select value={advTimestep} onChange={(e) => saveAdv({ timestep_type: e.target.value })}
                    aria-label="Timestep weighting"
                    className="px-2 py-1 rounded-lg border border-border bg-surface text-content text-[0.75rem]">
                    <option value="auto">Auto ({advTimestepDefault})</option>
                    {advTimestepChoices.map((t) => <option key={t} value={t}>{t}</option>)}
                  </select>
                </div>
                <span className="text-content-subtle text-[0.6875rem] leading-relaxed">
                  <b className="text-content-muted font-medium">Why:</b> which noise levels the loss emphasises — the
                  &quot;character&quot; knob for flow-matching models (Z-Image / Krea). <b className="text-content-muted font-medium">How:</b> Auto
                  = the tuned default ({advTimestepDefault}); <i>sigmoid</i> favours the subject, <i>shift</i>/<i>weighted</i> shift
                  the detail-vs-structure balance.
                </span>
              </div>
            )}
            {/* Optimizer */}
            <div className="flex flex-col gap-0.5">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-content text-[0.75rem] w-28 shrink-0">Optimizer</span>
                <select value={advOptimizer} onChange={(e) => saveAdv({ optimizer: e.target.value })}
                  aria-label="Optimizer"
                  className="px-2 py-1 rounded-lg border border-border bg-surface text-content text-[0.75rem]">
                  {advOptimizerChoices.map((o) => <option key={o} value={o}>{o}{o === 'adamw8bit' ? ' (default)' : ''}</option>)}
                </select>
              </div>
              <span className="text-content-subtle text-[0.6875rem] leading-relaxed">
                <b className="text-content-muted font-medium">Why:</b> how the weights are updated — the biggest training
                lever after the dataset. <b className="text-content-muted font-medium">How:</b> <i>adamw8bit</i> (default)
                is fast and VRAM-light; <i>adafactor</i> uses less memory and auto-scales; <i>automagic</i> sets the
                learning rate itself (no LR to tune, no extra install); <i>prodigy</i> also auto-tunes the LR and is
                popular for tiny sets — but may need <code className="text-content-muted">pip install prodigyopt</code> in
                the ai-toolkit venv. Picking an auto-LR optimiser is the &quot;push further without cranking the LR&quot; move.
              </span>
            </div>
            {/* LR schedule (+ warmup, only for the warmup schedule) */}
            <div className="flex flex-col gap-0.5">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-content text-[0.75rem] w-28 shrink-0">LR schedule</span>
                <select value={advLrSched} onChange={(e) => saveAdv({ lr_scheduler: e.target.value })}
                  aria-label="Learning-rate schedule"
                  className="px-2 py-1 rounded-lg border border-border bg-surface text-content text-[0.75rem]">
                  {advLrSchedChoices.map((s) => <option key={s} value={s}>{LR_SCHED_LABELS[s] || s}</option>)}
                </select>
                {advLrSched === 'constant_with_warmup' && (
                  <select value={String(advWarmup || 100)} onChange={(e) => saveAdv({ warmup: Number(e.target.value) })}
                    aria-label="Warmup steps"
                    className="px-2 py-1 rounded-lg border border-border bg-surface text-content text-[0.75rem]">
                    {advWarmupChoices.map((w) => <option key={w} value={String(w)}>{w} warmup</option>)}
                  </select>
                )}
              </div>
              <span className="text-content-subtle text-[0.6875rem] leading-relaxed">
                <b className="text-content-muted font-medium">Why:</b> how the learning rate moves over the run.
                <b className="text-content-muted font-medium"> How:</b> <i>Constant</i> (default) holds it flat;
                <i> Warmup → constant</i> ramps it up over the first N steps (a gentler start that avoids early
                over-commitment on a small set) then holds; <i>Linear</i>/<i>Cosine</i> decay it toward 0 by the end for
                cleaner convergence. The warmup-steps box only applies to the warmup schedule.
              </span>
            </div>
            {/* Gradient accumulation (effective batch) */}
            <div className="flex flex-col gap-0.5">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-content text-[0.75rem] w-28 shrink-0">Effective batch</span>
                <select value={String(advGradAccum)} onChange={(e) => saveAdv({ grad_accum: Number(e.target.value) })}
                  aria-label="Gradient accumulation"
                  className="px-2 py-1 rounded-lg border border-border bg-surface text-content text-[0.75rem]">
                  {advGradAccumChoices.map((g) => <option key={g} value={String(g)}>{g === 1 ? '1 (default)' : `${g} × accum`}</option>)}
                </select>
              </div>
              <span className="text-content-subtle text-[0.6875rem] leading-relaxed">
                <b className="text-content-muted font-medium">Why:</b> averages the gradient over N micro-batches before
                each update — a larger <i>effective</i> batch with no extra VRAM. <b className="text-content-muted font-medium">How:</b> 1
                (default); 2–4 smooths the noisy gradients a tiny dataset produces (steadier training), at the cost of a
                bit more time per update. A cheap stabiliser for small sets.
              </span>
            </div>
          </div>
        </details>

        <label className="flex items-center gap-1.5 text-[0.6875rem] text-content-muted cursor-pointer"
          title={concept
            ? 'For a CONCEPT dataset keep this OFF — a person mask would erase the very concept you are training. Masking only makes sense for a person/face LoRA.'
            : 'Masked training: a person mask is generated for every image (rembg, CPU) and the background only weighs 10% of the loss — identity binds to the face, not the room. Uncheck to train the old way.'}>
          <input type="checkbox" checked={masked} onChange={(e) => setMasked(e.target.checked)}
            aria-label="Masked training (background at 10%)"
            className="accent-primary w-3.5 h-3.5" />
          <span className={masked && !maskedRembgMissing ? 'text-emerald-300' : ''}>🎭 Masked (bg 10%)</span>
          {concept && masked && (
            <span className="text-amber-300" title="A person mask would erase the concept.">⚠️ off recommended for concepts</span>
          )}
          {maskedRembgMissing && (
            <span className="text-amber-300"
              title="rembg isn't installed, so no person masks can be generated — this run will train UNMASKED (background at full weight), not masked. Install Person masks from the Setup tab (Python 3.11–3.12) to enable masked training.">
              ⚠️ rembg missing — will train unmasked
            </span>
          )}
        </label>

        {!status.in_progress && keptCount >= 10 && (
          <label className="flex items-center gap-1.5 text-content-subtle text-[0.6875rem]"
            title={stepsInfo?.rationale
              ? `${stepsInfo.rationale} Leave empty to use it; applies to Train, Add to queue and Schedule.`
              : concept
                ? 'Target training steps. Leave empty for the adaptive value (sublinear 475·√images, capped 2000–12000): the bigger the set, the fewer views per image, so the LoRA generalizes instead of memorizing shots. Applies to Train, Add to queue and Schedule.'
                : 'Target training steps. Leave empty for the adaptive value (~120/image, capped 1500–3500). Set a lower cap (e.g. 2000) to stop earlier — it trains faster and lighter; then pick the best checkpoint in the Test Studio. Applies to Train, Add to queue and Schedule.'}>
            <span className="uppercase text-content-muted text-[0.625rem]">Steps</span>
            <input type="number" min={500} step={100}
              value={stepsOverride}
              onChange={(e) => setStepsOverride(e.target.value)}
              placeholder={String(stepsInfo?.steps ?? recoSteps)}
              aria-label="Target training steps (leave empty for adaptive)"
              className="w-[4.5rem] rounded border border-border bg-app/60 px-1.5 py-0.5 text-content tabular-nums text-[0.75rem]" />
            <span>{stepsOverride.trim() ? 'target' : `≈ adaptive (${keptCount} img)`}</span>
          </label>
        )}

        {status.installed && (
          <div className="flex items-center gap-2 flex-wrap">
            <button type="button" disabled={!launchConfigReady || keptCount < preflightFloor || queued || baseBlocksTrain || hasInvalidStepsOverride || !stepsOverrideValid} onClick={openSched}
              aria-expanded={showSched}
              title={baseBlocksTrain
                ? 'Convert the selected custom base first'
                : 'Schedule this training for a specific day and time — it will queue up if another training is running then'}
              className="px-3 py-1.5 rounded-lg bg-amber-500/15 border border-amber-400/40 text-amber-200 text-sm font-semibold disabled:opacity-40">
              {queued ? '✓ Queued' : '⏰ Schedule'}
            </button>
            <span className="text-content-subtle text-[0.625rem]">
              run this training later, at a day &amp; time you pick
            </span>
          </div>
        )}

        {showSched && !queued && (
          <div className="flex items-center gap-2 flex-wrap rounded-lg border border-amber-400/30 bg-amber-500/5 px-3 py-2">
            <label className="flex items-center gap-2 text-content-muted text-[0.6875rem]">
              <span className="uppercase">Start at</span>
              <input type="datetime-local" value={schedAt}
                onChange={(e) => setSchedAt(e.target.value)}
                aria-label="Scheduled training date and time"
                className="rounded border border-border bg-app/60 px-2 py-1 text-content text-[0.8125rem]" />
            </label>
            <span className="text-content-subtle text-[0.625rem]">
              Base « {baseLabel} » — if another training is running at that time, it waits in the queue.
            </span>
            <button type="button" onClick={schedule} disabled={!schedAt || !launchConfigReady}
              className="ml-auto px-3 py-1.5 rounded-lg bg-gradient-primary text-white text-sm font-semibold disabled:opacity-40">
              Schedule
            </button>
          </div>
        )}
      </div>
    </details>
  )
}
