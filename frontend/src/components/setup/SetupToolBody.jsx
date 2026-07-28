import { useState } from 'react'
import { putJson, postJson } from '../../api/fetchClient'
import GuidedSteps from './GuidedSteps'
import InstallRunner from './InstallRunner'
import LabeledConfigField from './LabeledConfigField'

const INPUT_CLASS =
  'mt-1 w-full rounded-md border border-border-strong bg-surface-raised px-3 py-2 text-sm text-content ' +
  'placeholder:text-content-subtle focus:border-primary focus:outline-none'
const KEY_FIELDS = [
  { key: 'GEMINI_API_KEY', label: 'Gemini API key', engine: 'nanobanana', href: 'https://aistudio.google.com/apikey', help: 'Powers Nano Banana.' },
  { key: 'OPENAI_API_KEY', label: 'OpenAI API key', engine: 'chatgpt', href: 'https://platform.openai.com/api-keys', help: 'Powers ChatGPT (gpt-image-2).' },
]
const DEFAULT_VISION_MODEL = 'huihui_ai/qwen3-vl-abliterated:8b-instruct'
const VISION_MODEL_VRAM = '≈ 8 GB VRAM'
const KLEIN_MODEL_VRAM = '≈ 16 GB VRAM (fp8; ~29 GB at bf16)'

/** Configuration and installation content for one setup tool. */
export default function SetupToolBody({ id, stepById, config, secretsPresence,
  setSecretsPresence, secretInputs, setSecretInputs, detected, busy, caps, refresh,
  toast, setField, persist, applyDetectedPath }) {
  const [startingOllama, setStartingOllama] = useState(false)
  // Test the key the user JUST typed. The probe reads the SAVED secret, so save
  // that one key first (no need to fill anything else), then test + re-probe so
  // the step flips to Ready. With no typed value, test whatever is already saved.
  const saveSecretThenTest = async (key, target) => {
    const typed = (secretInputs[key] || '').trim()
    try {
      if (typed) {
        const data = await putJson('/api/settings', { secrets: { [key]: typed } })
        setSecretsPresence(data.secrets)
        setSecretInputs((current) => (
          (current[key] || '').trim() === typed ? { ...current, [key]: '' } : current
        ))
      }
      const r = await postJson(`/api/settings/test/${target}`, {})
      r.ok ? toast.success(r.detail) : toast.warning(r.detail)
      await refresh(true)
    } catch (e) { toast.error(e.message) }
  }

  // One-click start for an ALREADY-INSTALLED Ollama that just isn't running
  // (caps.ollama.installed true, reachable false). The backend starts `ollama
  // serve` detached and polls readiness (~15s); refresh(true) then flips the step
  // to ready with no app restart. A failure returns 502 -> apiFetch throws (and
  // auto-toasts the generic 5xx notice); the catch adds the specific reason,
  // matching the existing saveSecretThenTest pattern.
  const startOllama = async () => {
    setStartingOllama(true)
    try {
      const r = await postJson('/api/ollama/start', {})
      if (r.reachable) { toast.success('Ollama started.'); await refresh(true) }
      else { toast.error(r.error || 'Ollama did not become ready.') }
    } catch (e) { toast.error(e.message || 'Could not start Ollama.') }
    finally { setStartingOllama(false) }
  }

  const guidedField = (label, section, key, placeholder) => (
    <LabeledConfigField label={label} value={config[section][key]} placeholder={placeholder}
      className={INPUT_CLASS} onChange={(value) => setField(section, key, value)} />
  )
  const saveRecheckBtn = (
    <button type="button" onClick={persist} disabled={busy}
      className="mt-1 rounded-md border border-border-strong px-3 py-1.5 text-xs font-medium text-content hover:bg-surface-raised disabled:opacity-50">
      {busy ? 'Saving…' : 'Save & re-check'}
    </button>
  )
  // "Found on disk: <path> — Use" chip for a scanned path we didn't auto-apply.
  const detectedPathChip = (section, key) => {
    const val = detected && detected[section] && detected[section][key]
    if (!val || (config[section] && config[section][key]) === val) return null
    return (
      <button type="button" onClick={() => applyDetectedPath(section, key, val)}
        className="mt-1 block text-left text-xs text-primary underline">
        Found on disk: <span className="font-mono">{val}</span> — Use
      </button>
    )
  }

  // --- Per-tool step body (reuses the existing controls, one tool per screen) ---
  const toolBody = (id) => {
    const step = stepById[id]
    if (id === 'image') {
      return (
        <div className="space-y-4">
          {KEY_FIELDS.map((f) => (
            <div key={f.key}>
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-content">{f.label}</span>
                <span className={`text-xs ${step.engines[f.engine] ? 'text-emerald-400' : 'text-content-subtle'}`}>
                  {step.engines[f.engine] ? '✓ Ready' : '○ Not set'}
                </span>
              </div>
              <p className="text-xs text-content-muted">{f.help}</p>
              <input type="password" autoComplete="off" className={INPUT_CLASS}
                aria-label={f.label}
                value={secretInputs[f.key] ?? ''}
                placeholder={secretsPresence[f.key] ? 'Already set — enter a new value to replace it' : 'Paste your key'}
                onChange={(e) => setSecretInputs((p) => ({ ...p, [f.key]: e.target.value }))} />
              <div className="mt-1 flex items-center gap-3">
                <a href={f.href} target="_blank" rel="noreferrer" className="text-xs text-primary underline">Get a key</a>
                <button type="button" onClick={() => saveSecretThenTest(f.key, f.engine === 'nanobanana' ? 'gemini' : 'openai')}
                  className="text-xs text-content-muted underline">Save &amp; test</button>
              </div>
            </div>
          ))}
          <p className="text-xs text-content-subtle">Klein (local) needs ComfyUI — the next step.</p>
          {saveRecheckBtn}
        </div>
      )
    }
    if (id === 'comfyui') {
      const fields = (
        <>
          {guidedField('ComfyUI API URL', 'comfyui', 'api_url', 'http://127.0.0.1:8188')}
          {guidedField('ComfyUI install directory', 'comfyui', 'base_dir', 'C:\\ComfyUI')}
          {detectedPathChip('comfyui', 'base_dir')}
          {/* Validate the folder on Save & re-check: it must actually hold main.py +
              models/. A portable-wrapper path is auto-corrected to the nested ComfyUI on
              save (so checkpoints are found); a genuinely wrong path is flagged here.
              The ✓/⚠ verdict comes from the last PROBE — while the field holds a path
              that hasn't been saved yet, showing that verdict would judge the WRONG
              string (a stale ⚠ next to a perfectly good typed path). Neutral hint then. */}
          {config.comfyui.base_dir && (
            config.comfyui.base_dir !== step.baseDir ? (
              <p className="text-xs text-content-subtle">
                Path not checked yet — <span className="text-content">Save &amp; re-check</span> to validate it.
              </p>
            ) : step.dirValid ? (
              <p className="text-xs text-emerald-400">
                ✓ ComfyUI found{step.resolvedDir ? <> at <span className="font-mono">{step.resolvedDir}</span></> : ''}.
              </p>
            ) : (
              <p className="text-xs text-amber-400">
                ⚠ No ComfyUI install in this folder — it must contain <span className="font-mono">main.py</span> and
                a <span className="font-mono">models/</span> folder. Check the path, then Save &amp; re-check.
                For the portable build, point at the inner <span className="font-mono">…\ComfyUI_windows_portable\ComfyUI</span>.
              </p>
            )
          )}
          {step.reachable && !step.hasKlein && (
            <div className="space-y-1 text-xs text-content-muted">
              <p>
                Running. The Klein model is <span className="text-content font-medium">optional</span> — add it only if you want
                local generation (you can also use the API engines or your own photos, then export to train elsewhere).
                To enable it, download <span className="font-mono">flux-2-klein-9b-fp8.safetensors</span> ({KLEIN_MODEL_VRAM}) into
                <span className="font-mono"> &lt;ComfyUI&gt;/models/unet/klein/</span>.
              </p>
              <p>
                Also recommended: the <span className="text-content font-medium">consistency LoRA</span>{' '}
                <span className="font-mono">Flux2-Klein-9B-consistency-V2.safetensors</span> (331 MB) into{' '}
                <span className="font-mono">&lt;ComfyUI&gt;/models/loras/klein/</span> — it anchors the composition between
                edits (the "Consistency LoRA" slider drives its strength; ~0.5 is balanced, high values suppress
                pose changes). Face identity itself comes from the reference photo(s).
              </p>
              {step.dirValid ? (
                <div className="space-y-2 rounded-md border border-border bg-white/5 p-2.5">
                  <p className="text-content text-xs font-medium">
                    ⬇ One-click downloads — straight into the validated ComfyUI folders:
                  </p>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <p className="mb-1 text-[0.6875rem] text-content-muted">
                        Klein model (fp8) → <span className="font-mono">models/unet/klein/</span>
                        <span className="block text-amber-300/90">
                          License-gated: accept it on the official page, then add an HF_TOKEN in Settings → Image engines.
                        </span>
                      </p>
                      <InstallRunner action="klein_model" buttonLabel="⬇ Download Klein model"
                        onDone={() => refresh(true)} />
                    </div>
                    <div>
                      <p className="mb-1 text-[0.6875rem] text-content-muted">
                        Consistency LoRA (331 MB) → <span className="font-mono">models/loras/klein/</span>
                      </p>
                      <InstallRunner action="klein_lora" buttonLabel="⬇ Download consistency LoRA"
                        onDone={() => refresh(true)} />
                    </div>
                    <div>
                      <p className="mb-1 text-[0.6875rem] text-content-muted">
                        Text encoder (~8.7 GB) → <span className="font-mono">models/text_encoders/</span>
                      </p>
                      <InstallRunner action="klein_text_encoder" buttonLabel="⬇ Download text encoder"
                        onDone={() => refresh(true)} />
                    </div>
                    <div>
                      <p className="mb-1 text-[0.6875rem] text-content-muted">
                        VAE (336 MB) → <span className="font-mono">models/vae/</span>
                      </p>
                      <InstallRunner action="klein_vae" buttonLabel="⬇ Download VAE"
                        onDone={() => refresh(true)} />
                    </div>
                  </div>
                </div>
              ) : (
                <p className="text-xs text-content-subtle">
                  Validate the ComfyUI install directory above (Save &amp; re-check) to unlock one-click downloads.
                </p>
              )}
              <p className="flex flex-wrap gap-x-4 gap-y-1">
                <a href="https://huggingface.co/black-forest-labs/FLUX.2-klein-9b-fp8" target="_blank" rel="noreferrer"
                  className="text-primary underline">Official Klein model page →</a>
                <a href="https://huggingface.co/dx8152/Flux2-Klein-9B-Consistency" target="_blank" rel="noreferrer"
                  className="text-primary underline">Official consistency LoRA page →</a>
                <a href="https://docs.comfy.org/tutorials/flux/flux-2-klein" target="_blank" rel="noreferrer"
                  className="text-primary underline">ComfyUI setup guide →</a>
              </p>
            </div>
          )}
          {saveRecheckBtn}
        </>
      )
      // Already detected/running → skip the from-scratch install guide; show the
      // reachable confirmation and only the remaining gap.
      if (step.reachable) {
        return (
          <div className="space-y-4">
            <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-content">
              ✓ ComfyUI is already running at <span className="font-mono">{step.apiUrl || 'the configured URL'}</span>.
              {step.hasKlein ? ' Nothing to do here.' : ' It works — the Klein model (optional, for local generation) isn’t installed.'}
            </div>
            {fields}
          </div>
        )
      }
      return (
        <GuidedSteps
          intro="ComfyUI is a local image generator. Install it once, then point the app at it."
          steps={[
            { text: 'Clone ComfyUI and follow its README to install it.', command: 'git clone https://github.com/comfyanonymous/ComfyUI' },
            { text: 'Start it (defaults to port 8188).' },
          ]}
          link={{ href: 'https://github.com/comfyanonymous/ComfyUI', label: 'ComfyUI on GitHub →' }}>
          {fields}
        </GuidedSteps>
      )
    }
    if (id === 'ollama') {
      // The vision MODEL is the point, not just Ollama being up. When reachable but
      // the model isn't pulled, lead with the pull action (this is the required gate).
      const model = step.visionModel || DEFAULT_VISION_MODEL
      const pullBlock = step.reachable && !step.visionModelReady && (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3">
          <p className="mb-1 text-sm font-medium text-content">
            Ollama is running, but the vision model isn't pulled yet — that's what powers captioning.
          </p>
          <p className="mb-2 text-xs text-content-muted">
            <span className="font-mono">{model}</span> — uncensored, needed for concept captions · {VISION_MODEL_VRAM}
          </p>
          <InstallRunner action="ollama_model" buttonLabel={`Pull ${model}`}
            manualCommand={`ollama pull ${model}`}
            onDone={() => refresh(true)} />
        </div>
      )
      const fields = (
        <>
          {guidedField('Ollama URL', 'ollama', 'url', 'http://127.0.0.1:11434')}
          {guidedField('Vision model', 'ollama', 'vision_model', DEFAULT_VISION_MODEL)}
          <p className="text-xs text-content-subtle">
            Use the ABLITERATED Qwen3-VL ({VISION_MODEL_VRAM}) — the vanilla model refuses NSFW.
            For the best captions the app pairs it with JoyCaption (ai-toolkit) — a Joy+Ollama combo.
          </p>
          {saveRecheckBtn}
        </>
      )
      if (step.reachable) {
        return (
          <div className="space-y-4">
            {step.visionModelReady ? (
              <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-content">
                ✓ Ollama is running at <span className="font-mono">{step.url || 'the configured URL'}</span> and
                the vision model <span className="font-mono">{step.visionModel}</span> is ready. Nothing to do here.
              </div>
            ) : pullBlock}
            {fields}
          </div>
        )
      }
      // Installed but not running → a one-click Start beats sending the user back
      // to the install guide (the binary is detected independently of the server).
      if (step.installed) {
        return (
          <div className="space-y-4">
            <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3">
              <p className="mb-1 text-sm font-medium text-content">
                Ollama is installed{step.binaryPath && (
                  <> at <span className="font-mono">{step.binaryPath}</span></>
                )} but not running.
              </p>
              <p className="mb-2 text-xs text-content-muted">
                Start it (it listens on port 11434) to unlock captioning and auto-framing — no restart needed.
              </p>
              <button type="button" onClick={startOllama} disabled={startingOllama}
                className="rounded-md bg-gradient-primary px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50">
                {startingOllama ? 'Starting…' : '▶ Start Ollama'}
              </button>
            </div>
            {fields}
          </div>
        )
      }
      return (
        <GuidedSteps
          intro="Ollama runs local models for captioning and auto-framing. Installing it is not enough — you also need to pull a vision model."
          steps={[{ text: 'Install Ollama and start it (defaults to port 11434).' }]}
          link={{ href: 'https://ollama.com/download', label: 'Download Ollama →' }}>
          {fields}
        </GuidedSteps>
      )
    }
    if (id === 'quality') {
      // Each ML helper installs — or REINSTALLS/repairs — on its own now, so a user
      // who's missing just one (e.g. watermark inpainting on an older install) fixes
      // that one without redoing the whole monolithic step. The all-at-once install
      // stays available below for a first-time setup.
      const ML_CAPS = [
        { action: 'face_scoring', cap: 'face_scoring', icon: '🎭', title: 'Face-similarity scoring',
          body: 'Powers the "Analyze faces" pass: scores how closely each generated image resembles your reference photo, so you keep the ones that truly look like the person. It only ranks — it never deletes anything.' },
        { action: 'masks', cap: 'masks', icon: '🧍', title: 'Person masks',
          body: 'Isolates the subject from the background for masked training: the décor is weighted down so the LoRA binds the identity to the person, not the room. A training without masks is still valid.' },
        { action: 'watermark_inpaint', cap: 'watermark_inpaint', icon: '🧽', title: 'Watermark inpainting',
          body: 'Repaints small off-center watermarks (LaMa) during 🧽 Clean instead of only cropping border marks. It can use CUDA or CPU from Settings. Without it, off-center marks are skipped.' },
      ]
      return (
        <div className="space-y-3">
          <p className="text-sm text-content-muted">
            Optional helpers installed into this app's own Python environment. Face scoring and masks run on
            CPU; watermark inpainting can use CUDA or CPU. The app works fully without them; they just make
            curation and training cleaner. Install each on its own below, or all at once at the bottom. Already installed?
            Use <span className="font-medium text-content">↻ Reinstall</span> to repair or update it.
          </p>
          {caps.python && !caps.python.ml_supported && (
            <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2.5 text-sm text-content space-y-1">
              <p>
                <span className="font-semibold text-amber-300">⚠ Python {caps.python.version} —</span>{' '}
                these extras need Python {caps.python.ml_range}. The reviewed InsightFace, rembg, ONNX and
                Torch dependency graph is not supported on {caps.python.version}, so the installs below will fail.
              </p>
              <p className="text-content-muted">
                They're optional — you can skip this step, or install them into a separate Python 3.11/3.12
                environment and point <span className="font-mono">face_scoring.python</span> +{' '}
                <span className="font-mono">masks.python</span> at it in Settings → Local tools.
              </p>
            </div>
          )}
          <div className="space-y-3">
            {ML_CAPS.map((c) => {
              const present = !!caps[c.cap]
              return (
                <div key={c.action} className="rounded-md border border-border bg-surface-raised p-3 space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-semibold text-content">{c.icon} {c.title}</span>
                    <span className={`shrink-0 text-xs font-medium ${present ? 'text-emerald-400' : 'text-content-subtle'}`}>
                      {present ? '✓ Installed' : '✗ Not installed'}
                    </span>
                  </div>
                  <p className="text-xs text-content-muted">{c.body}</p>
                  {/* Reuse the Setup InstallRunner verbatim — polling, live pip log, and the
                      scoped manual-command fallback come from the backend per action. onDone
                      re-probes caps so ✗ flips to ✓ (or the reinstall confirms) without a restart. */}
                  <InstallRunner action={c.action}
                    buttonLabel={present ? '↻ Reinstall' : 'Install'}
                    onDone={() => refresh(true)} />
                </div>
              )
            })}
          </div>
          <details className="rounded-md border border-border bg-surface-raised px-3 py-2">
            <summary className="cursor-pointer text-xs text-content-subtle hover:text-content">
              Or install everything at once (first-time setup)
            </summary>
            <div className="mt-2">
              <InstallRunner action="ml_extras" buttonLabel="Install all (pip)"
                manualCommand="python -m pip install -r backend/requirements-ml.txt" onDone={() => refresh(true)} />
            </div>
          </details>
        </div>
      )
    }
    // training (ai-toolkit)
    const dir = (config.aitoolkit && config.aitoolkit.dir) || ''
    const detectedDir = detected && detected.aitoolkit && detected.aitoolkit.dir
    const fields = (
      <>
        {guidedField('ai-toolkit directory', 'aitoolkit', 'dir', 'C:\\ai-toolkit')}
        {saveRecheckBtn}
        <p className="mt-2 text-content-muted text-xs">
          No GPU? You can skip this step: add a <strong>vast.ai API key</strong> in
          Settings instead and train in the cloud (the app rents a GPU per run,
          typically ~$1-2). It requests shutdown when work ends and keeps the run visibly billable until vast.ai confirms it.
        </p>
      </>
    )
    if (step.valid) {
      return (
        <div className="space-y-4">
          <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-content">
            ✓ ai-toolkit is set up at <span className="font-mono">{dir}</span>. Nothing to do here.
          </div>
          {fields}
        </div>
      )
    }
    // Found on disk but not applied yet → one prominent click (not a subtle link).
    if (detectedDir && dir !== detectedDir) {
      return (
        <div className="space-y-4">
          <div className="rounded-md border border-primary/40 bg-primary/10 px-3 py-3 text-sm text-content">
            <p className="mb-2">Found an ai-toolkit install at <span className="font-mono">{detectedDir}</span>. Use it?</p>
            <button type="button" onClick={() => applyDetectedPath('aitoolkit', 'dir', detectedDir)}
              className="rounded-lg bg-gradient-primary px-4 py-1.5 text-xs font-semibold text-white">
              Use this ai-toolkit →
            </button>
          </div>
          {fields}
        </div>
      )
    }
    // Pointed at a folder that isn't usable yet (venv missing) → finish it, don't re-clone.
    if (dir) {
      return (
        <div className="space-y-4">
          <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-content">
            Pointed at <span className="font-mono">{dir}</span>, but it isn't usable yet — set up its Python venv per the README.
          </div>
          {fields}
        </div>
      )
    }
    return (
      <GuidedSteps
        intro="ai-toolkit trains the LoRA. Install it once, then point the app at its folder."
        steps={[
          { text: 'Clone ai-toolkit and set up its venv per its README.', command: 'git clone https://github.com/ostris/ai-toolkit' },
        ]}
        link={{ href: 'https://github.com/ostris/ai-toolkit', label: 'ai-toolkit on GitHub →' }}>
        {fields}
      </GuidedSteps>
    )
  }

  return toolBody(id)
}
