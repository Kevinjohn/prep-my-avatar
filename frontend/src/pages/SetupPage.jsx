import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { writeSession } from '../utils/sessionStorage'
import { useToast } from '../components/common/Toast'
import { useConfirmDialog } from '../components/common/ConfirmDialog'
import { useCapabilities } from '../context/CapabilitiesContext'
import { deriveSetupSteps, deriveCapabilitySummary, SETUP_STEP_IDS } from '../hooks/useSetupSteps'
import { useSetupSettings } from '../hooks/useSetupSettings'
import SetupToolBody from '../components/setup/SetupToolBody'
import { ollamaGateReason, setupNavigation } from '../utils/setupWorkflow'

// A wizard "screen" is the welcome/scan, one per setup tool, then done.
const TOTAL_TOOLS = SETUP_STEP_IDS.length

const STATUS_META = {
  ready: { glyph: '✓', label: 'Ready', cls: 'text-emerald-400' },
  partial: { glyph: '◐', label: 'Almost there', cls: 'text-amber-400' },
  available: { glyph: '○', label: 'Not set up', cls: 'text-content-subtle' },
}

// Map each capability in the "What's unlocked" review list (deriveCapabilitySummary,
// useSetupSteps.js) back to the wizard step that installs/configures it, so clicking a
// row jumps straight to that step. Most entries match a step's own `unlocks` wording
// 1:1 (Captioning, Face-similarity scoring, Person masks, LoRA training, Test Studio).
// Two don't, and are set by where the control actually lives: "Klein (local)" is
// downloaded from the comfyui step's body (toolBody('comfyui') has the one-click
// installers), not the image step — the image step only has the API-key fields and a
// note pointing at ComfyUI. "Auto-framing & head-crop" is the ollama step's other two
// unlocks (Auto-classify framing / Auto head-crop), just phrased differently here.
const CAPABILITY_STEP_ID = {
  'Nano Banana (Gemini)': 'image',
  'ChatGPT (gpt-image-2)': 'image',
  'Klein (local)': 'comfyui',
  'Captioning': 'ollama',
  'Auto-framing & head-crop': 'ollama',
  'Face-similarity scoring': 'quality',
  'Person masks': 'quality',
  'Watermark inpainting': 'quality',
  'LoRA training': 'training',
  'Test Studio': 'comfyui',
}

export default function SetupPage() {
  const toast = useToast()
  const confirm = useConfirmDialog()
  const { caps, refresh } = useCapabilities()
  const {
    config, secretsPresence, setSecretsPresence, secretInputs, setSecretInputs,
    busy, loadError, detected, detecting, scanned, scanError, dirty, load, runAutodetect,
    setField, persist, applyDetectedPath,
  } = useSetupSettings({ refresh, toast })
  const [screen, setScreen] = useState(0)           // index into SCREENS
  const [advancing, setAdvancing] = useState(false) // Next is mid save-&-recheck
  const steps = useMemo(() => deriveSetupSteps(caps), [caps])
  const summary = useMemo(() => deriveCapabilitySummary(caps), [caps])
  const readyCount = summary.filter((s) => s.ok).length
  const stepById = useMemo(() => Object.fromEntries(steps.map((s) => [s.id, s])), [steps])

  if (!config) {
    return loadError ? (
      <div className="space-y-3">
        <p className="text-content-muted">Couldn't load setup.</p>
        <button type="button" onClick={load}
          className="rounded-md border border-border-strong px-3 py-1.5 text-sm font-medium text-content hover:bg-surface-raised">
          Retry
        </button>
      </div>
    ) : (
      <p className="text-content-muted">Loading setup…</p>
    )
  }

  const {
    kind, done: DONE, isReady, toolIndex: toolIdx, screenOf, allReady,
    firstUnfinished, nextUnfinished, previousUnfinished: prevUnfinished,
  } = setupNavigation(SETUP_STEP_IDS, stepById, screen)
  // Captioning is the ONE capability the wizard insists on. Z-Image (the default
  // training type) needs Ollama's vision model for prose captions — JoyCaption only
  // covers SDXL booru tags — so the Ollama gate does NOT lift just because JoyCaption
  // is present. The MODEL, not merely Ollama being up, is what matters. Nothing else
  // is hard-gated (build from your own photos + export to train elsewhere stays open).
  // The global "Skip setup" link is still the deliberate bail-out.
  // Pure gate check on a derived step object, so it can be re-evaluated against FRESH
  // capabilities after a save (not just the render-time snapshot).
  const blockReason = (id) => (id === 'ollama' ? ollamaGateReason(stepById.ollama) : null)
  // The scan already knows what's installed — so "Start setup" / Next land on the
  // first tool that still needs attention and skip the ones already ready. No
  // re-walking ComfyUI/Ollama when they were just detected as running.
  const startSetup = () => {
    const first = firstUnfinished
    setScreen(first ? screenOf(first) : DONE)
  }
  const goNext = () => {
    if (kind === 'welcome') return startSetup()
    if (kind === 'done') return
    const nxt = nextUnfinished(toolIdx(kind))
    setScreen(nxt ? screenOf(nxt) : DONE)
  }
  // Guard-rail: Back (unlike Save & continue) does NOT save — warn before losing
  // typed-but-unsaved fields (config edits or a typed secret).
  const hasUnsaved = () => dirty
  const goBack = async () => {
    if (hasUnsaved() && !(await confirm({
      title: 'Discard unsaved setup changes?',
      message: 'The values typed on this step have not been saved and will be lost if you go back.',
      confirmLabel: 'Discard and go back',
      tone: 'danger',
    }))) return
    if (kind === 'done') {
      const last = [...SETUP_STEP_IDS].reverse().find((id) => !isReady(id))
      return setScreen(last ? screenOf(last) : 0)
    }
    const prv = prevUnfinished(toolIdx(kind))
    setScreen(prv ? screenOf(prv) : 0)
  }
  // Next on a tool step SAVES + re-checks first (so typed URLs/models take effect and
  // the status refreshes), then advances — unless a required gate is still unmet after
  // the re-check, in which case it stays and says why. Re-evaluates against FRESHLY
  // fetched capabilities because the context update from persist() is async.
  const nextWithSave = async () => {
    setAdvancing(true)
    try {
      const fresh = await persist()
      if (!fresh) {
        toast.warning('Setup was not saved and rechecked. Fix the connection and try again.')
        return
      }
      if (kind === 'ollama') {
        const reason = ollamaGateReason(deriveSetupSteps(fresh).find((x) => x.id === 'ollama'))
        if (reason) { toast.warning(reason); return }
      }
      goNext()
    } finally { setAdvancing(false) }
  }

  // Progress dots: one per tool step, filled when that tool is ready.
  const ProgressDots = () => (
    <div className="flex items-center gap-1.5" aria-hidden="true">
      {SETUP_STEP_IDS.map((id) => {
        const active = kind === id
        const ready = stepById[id].status === 'ready'
        return (
          <span key={id}
            className={`h-2 rounded-full transition-all ${active ? 'w-6 bg-primary'
              : ready ? 'w-2 bg-emerald-400' : 'w-2 bg-border-strong'}`} />
        )
      })}
    </div>
  )

  const skipLink = (
    // Defense in depth: also mark the onboarding redirect as "already fired" here,
    // in the same sessionStorage key App.jsx's OnboardingRedirect guards on — so
    // skipping never bounces straight back to #/setup even in an edge case where
    // the guard effect hasn't run yet (e.g. this Link navigates before that effect
    // re-fires with fresh caps).
    <Link to="/datasets" onClick={() => writeSession('lds_setup_redirected', '1')}
      className="text-xs text-content-subtle underline hover:text-content">
      Skip setup — I'll do it later
    </Link>
  )

  // --- Welcome + live machine scan --------------------------------------------
  if (kind === 'welcome') {
    // Three states per tool: ready (✓ green), partial (⚠ amber — detected but a
    // key piece is missing), missing (✗). Ollama keys on the MODEL, not just being
    // reachable — a running Ollama with no vision model is only "partial".
    // `optional: true` rows (local generation) never look like a problem when not
    // ready — you can build a dataset from your own photos + API engines and export
    // to train elsewhere. They render neutral (grey ○ + "optional"), not amber/✗.
    const triState = (reachable, complete) => reachable ? (complete ? 'ready' : 'partial') : 'missing'
    // Ollama now has THREE scan outcomes: running (ready, or amber "pull the model"),
    // installed-but-STOPPED (amber "installed — not running" → the ollama step's ▶ Start
    // button fixes it), and genuinely absent (✗). The old triState collapsed the stopped
    // case into "✗ not found", which read as "you don't have Ollama".
    const oll = stepById.ollama
    const ollamaScan = oll.reachable
      ? { state: oll.visionModelReady ? 'ready' : 'partial', partial: 'running — pull the vision model' }
      : oll.installed
        ? { state: 'partial', partial: 'installed — not running' }
        : { state: 'missing', partial: '' }
    // stepId: which wizard step (SETUP_STEP_IDS) installs/configures this capability —
    // each row is a direct link to that step's screen, whether or not it's ready yet.
    const scanRows = [
      { label: 'Local generation — ComfyUI', optional: true, stepId: 'comfyui',
        state: triState(stepById.comfyui.reachable, stepById.comfyui.hasKlein),
        partial: 'running — Klein model optional' },
      { label: 'Captioning — Ollama + vision model', stepId: 'ollama',
        state: ollamaScan.state, partial: ollamaScan.partial },
      { label: 'LoRA training — ai-toolkit', stepId: 'training',
        state: stepById.training.valid ? 'ready'
          : (detected && detected.aitoolkit && detected.aitoolkit.dir ? 'partial' : 'missing'),
        partial: 'found on disk — one click to use' },
    ]
    const SCAN_META = {
      ready: { glyph: '✓', cls: 'text-emerald-400', word: 'ready' },
      partial: { glyph: '⚠', cls: 'text-amber-400', word: '' },
      missing: { glyph: '✗', cls: 'text-content-subtle', word: 'not found' },
    }
    // Optional + not-ready → don't alarm: neutral glyph/color and an "optional" tone.
    const NEUTRAL = { glyph: '○', cls: 'text-content-subtle' }
    return (
      <div className="mx-auto max-w-2xl space-y-6">
        <div className="text-center">
          <div className="text-3xl" aria-hidden="true">🧬</div>
          <h1 className="mt-2 text-2xl font-bold text-content">Welcome to Prep My Avatar</h1>
          <p className="mt-2 text-sm text-content-muted">
            Let's set up your machine. I'll scan what's already installed and help you install the rest —
            you can also start building a dataset from your own photos right now, no setup required.
          </p>
        </div>

        <section className="rounded-xl border border-border bg-surface p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-content">
              {detecting ? 'Scanning your machine…' : 'Machine scan'}
            </h2>
            {detecting
              ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-border-strong border-t-primary" aria-hidden="true" />
              : (
                <button type="button" onClick={() => runAutodetect(config)}
                  className="text-xs text-primary underline">Re-scan</button>
              )}
          </div>
          <ul className="mt-4 space-y-1">
            {scanRows.map((r) => {
              const soft = r.optional && r.state !== 'ready'   // optional + not ready → neutral, not a warning
              const m = soft ? { ...SCAN_META[r.state], ...NEUTRAL } : SCAN_META[r.state]
              const word = r.state === 'partial' ? r.partial
                : r.state === 'missing' ? (r.optional ? 'optional' : m.word)
                : m.word
              return (
                <li key={r.label}>
                  {/* Whole row navigates to the wizard step that installs this capability —
                      ready ones stay clickable too (revisit/change it), the chevron just
                      stays subtle for those. Disabled mid-scan: the state is still shifting. */}
                  <button type="button" disabled={detecting}
                    onClick={() => setScreen(screenOf(r.stepId))}
                    className="flex w-full items-center justify-between gap-3 rounded-md px-2 py-1.5 -mx-2 text-left text-sm
                      cursor-pointer transition-colors hover:bg-surface-raised focus:outline-none focus-visible:ring-2
                      focus-visible:ring-primary disabled:cursor-default disabled:hover:bg-transparent">
                    <span className="flex items-center gap-2">
                      <span aria-hidden="true" className={detecting ? 'text-content-subtle' : m.cls}>
                        {detecting ? '…' : m.glyph}
                      </span>
                      <span className={r.state === 'ready' ? 'text-content' : 'text-content-muted'}>{r.label}</span>
                      {r.optional && (
                        <span className="rounded bg-surface-raised px-1.5 py-px text-[10px] font-medium text-content-subtle">optional</span>
                      )}
                    </span>
                    <span className="flex items-center gap-1.5">
                      <span className={`truncate text-right font-mono text-xs ${detecting ? 'text-content-subtle' : m.cls}`}>
                        {detecting ? '' : word}
                      </span>
                      {!detecting && (
                        <span aria-hidden="true"
                          className={`text-xs ${r.state === 'ready' ? 'text-content-subtle/60' : 'text-content-subtle'}`}>
                          ›
                        </span>
                      )}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
          {scanError && !detecting && (
            <div role="alert" className="mt-3 flex items-center justify-between gap-3 text-xs text-rose-400">
              <span>Machine scan failed: {scanError}</span>
              <button type="button" onClick={() => runAutodetect(config)} className="shrink-0 underline">Retry scan</button>
            </div>
          )}
          {scanned && !detecting && !scanError && (
            <p className="mt-3 text-xs text-content-subtle">
              {readyCount} of {summary.length} capabilities ready. Reachable services were filled in automatically.
            </p>
          )}
        </section>

        <div className="flex items-center justify-between">
          {skipLink}
          <button type="button" onClick={goNext}
            className="rounded-lg bg-gradient-primary px-5 py-2 text-sm font-semibold text-white">
            {allReady ? "Everything's ready — review →" : 'Start setup →'}
          </button>
        </div>
      </div>
    )
  }

  // --- Done / summary ----------------------------------------------------------
  if (kind === 'done') {
    return (
      <div className="mx-auto max-w-2xl space-y-6">
        <div className="text-center">
          <div className="text-3xl" aria-hidden="true">🎉</div>
          <h1 className="mt-2 text-2xl font-bold text-content">You're all set</h1>
          <p className="mt-1 text-sm text-content-muted">{readyCount} of {summary.length} capabilities ready.</p>
        </div>
        <section className="rounded-xl border border-border bg-surface p-5">
          <h2 className="text-base font-semibold text-content">What's unlocked</h2>
          <ul className="mt-3 grid gap-1 sm:grid-cols-2">
            {summary.map((s) => {
              const targetStep = CAPABILITY_STEP_ID[s.label]
              // Every current capability maps to a wizard step (see CAPABILITY_STEP_ID above);
              // this guard is defensive only — an unmapped label just renders inert, as before.
              if (!targetStep) {
                return (
                  <li key={s.label} className={`flex items-center gap-2 px-2 py-1 text-sm ${s.ok ? 'text-content' : 'text-content-subtle'}`}>
                    <span aria-hidden="true" className={s.ok ? 'text-emerald-400' : 'text-content-subtle'}>{s.ok ? '✓' : '✗'}</span>
                    {s.label}
                  </li>
                )
              }
              return (
                <li key={s.label}>
                  <button type="button" onClick={() => setScreen(screenOf(targetStep))}
                    className={`flex w-full items-center justify-between gap-2 rounded-md px-2 py-1 text-left text-sm
                      cursor-pointer transition-colors hover:bg-surface-raised focus:outline-none focus-visible:ring-2
                      focus-visible:ring-primary ${s.ok ? 'text-content' : 'text-content-subtle'}`}>
                    <span className="flex items-center gap-2">
                      <span aria-hidden="true" className={s.ok ? 'text-emerald-400' : 'text-content-subtle'}>{s.ok ? '✓' : '✗'}</span>
                      {s.label}
                    </span>
                    <span aria-hidden="true" className={`text-xs ${s.ok ? 'text-content-subtle/60' : 'text-content-subtle'}`}>›</span>
                  </button>
                </li>
              )
            })}
          </ul>
        </section>
        <div className="flex items-center justify-between">
          <button type="button" onClick={goBack} className="text-xs text-content-subtle underline hover:text-content">
            ← Back
          </button>
          <Link to="/datasets" className="rounded-lg bg-gradient-primary px-5 py-2 text-sm font-semibold text-white">
            Build your first dataset →
          </Link>
        </div>
      </div>
    )
  }

  // --- A single tool step ------------------------------------------------------
  const step = stepById[kind]
  const stepNo = SETUP_STEP_IDS.indexOf(kind) + 1
  const meta = STATUS_META[step.status] || STATUS_META.available
  const reason = blockReason(kind)                 // live hint of what's still missing
  const hasNext = nextUnfinished(toolIdx(kind)) !== null
  // Next always saves + re-checks first; the gate (if any) is enforced AFTER that
  // fresh re-check inside nextWithSave, not by disabling the button on a stale snapshot.
  const nextLabel = advancing ? 'Saving…' : (hasNext ? 'Save & continue →' : 'Save & finish →')
  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <div className="flex items-center justify-between">
        <ProgressDots />
        <span className="text-xs text-content-subtle">Step {stepNo} of {TOTAL_TOOLS}</span>
      </div>

      <section className="rounded-xl border border-border bg-surface p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-content">
              {step.title}
              {step.recommended && (
                <span className="ml-2 rounded bg-primary/15 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                  Recommended
                </span>
              )}
            </h1>
            <p className="mt-1 text-xs text-content-muted">Unlocks: {step.unlocks.join(' · ')}</p>
          </div>
          <span className={`inline-flex shrink-0 items-center gap-1 text-xs font-medium ${meta.cls}`}>
            <span aria-hidden="true">{meta.glyph}</span>{meta.label}
          </span>
        </div>
        <div className="mt-4">
          <SetupToolBody id={kind} stepById={stepById} config={config}
            secretsPresence={secretsPresence} setSecretsPresence={setSecretsPresence}
            secretInputs={secretInputs} setSecretInputs={setSecretInputs}
            detected={detected} busy={busy} caps={caps} refresh={refresh} toast={toast}
            setField={setField} persist={persist} applyDetectedPath={applyDetectedPath} />
        </div>
      </section>

      {reason && (
        <p className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
          🔒 {reason}
        </p>
      )}
      <div className="flex items-center justify-between">
        <button type="button" onClick={goBack} className="text-xs text-content-subtle underline hover:text-content">
          ← Back
        </button>
        <div className="flex items-center gap-4">
          {skipLink}
          <button type="button" onClick={nextWithSave} disabled={advancing}
            title={reason || ''}
            className="rounded-lg bg-gradient-primary px-5 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40">
            {nextLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
