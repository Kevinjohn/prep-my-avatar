import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { SETUP_REDIRECT_SESSION_KEY, writeSession } from '../utils/sessionStorage'
import { useToast } from '../components/common/Toast'
import { useConfirmDialog } from '../components/common/ConfirmDialog'
import { useCapabilities } from '../context/CapabilitiesContext'
import {
  deriveSessionStatus, deriveSetupGroups, deriveSetupSteps, SETUP_STEP_IDS,
} from '../hooks/useSetupSteps'
import { useSetupSettings } from '../hooks/useSetupSettings'
import SetupToolBody from '../components/setup/SetupToolBody'
import { detailBackScreen, localVisionGateReason, setupNavigation } from '../utils/setupWorkflow'

// A wizard "screen" is the welcome/scan, one per setup tool, then done.
const TOTAL_TOOLS = SETUP_STEP_IDS.length

const STATUS_META = {
  ready: { glyph: '✓', label: 'Ready', cls: 'text-emerald-400' },
  partial: { glyph: '◐', label: 'Almost there', cls: 'text-amber-400' },
  available: { glyph: '○', label: 'Not set up', cls: 'text-content-subtle' },
}

export default function SetupPage() {
  const toast = useToast()
  const confirm = useConfirmDialog()
  const { caps, loading: capabilitiesLoading, error: capabilitiesError, refresh } = useCapabilities()
  const {
    config, secretsPresence, setSecretsPresence, secretInputs, setSecretInputs,
    busy, loadError, detected, detecting, scanned, scanError, dirty, load, runAutodetect,
    setField, persist, applyDetectedPath,
  } = useSetupSettings({ refresh, toast })
  const [screen, setScreen] = useState(0)           // index into SCREENS
  const [detailOrigin, setDetailOrigin] = useState(null)
  const [advancing, setAdvancing] = useState(false) // Next is mid save-&-recheck
  const steps = useMemo(() => deriveSetupSteps(caps), [caps])
  const setupGroups = useMemo(() => deriveSetupGroups(steps), [steps])
  const sessionRows = useMemo(() => deriveSessionStatus(steps), [steps])
  const sessionReadyCount = sessionRows.filter((row) => row.ready).length
  const coreSetupComplete = setupGroups.filter((group) => group.required).every((group) => group.complete)
  const optionalConfiguredCount = steps.filter((step) =>
    ['quality', 'training'].includes(step.id) && step.setupComplete).length
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
    kind, done: DONE, isReady, toolIndex: toolIdx, screenOf,
    nextUnfinished, previousUnfinished: prevUnfinished,
  } = setupNavigation(SETUP_STEP_IDS, stepById, screen)
  // Captioning is the ONE capability the wizard insists on. Z-Image (the default
  // training type) needs Ollama's vision model for prose captions — JoyCaption only
  // covers SDXL booru tags — so the Ollama gate does NOT lift just because JoyCaption
  // is present. The MODEL, not merely Ollama being up, is what matters. Nothing else
  // is hard-gated (build from your own photos + export to train elsewhere stays open).
  // The global "Skip setup" link is still the deliberate bail-out.
  // Pure gate check on a derived step object, so it can be re-evaluated against FRESH
  // capabilities after a save (not just the render-time snapshot).
  const blockReason = (id) => (id === 'ollama' && !stepById.ollama.setupComplete
    ? localVisionGateReason(stepById.ollama) : null)
  // The scan already knows what's installed — so "Start setup" / Next land on the
  // first tool that still needs attention and skip the ones already ready. No
  // re-walking ComfyUI/Ollama when they were just detected as running.
  const startSetup = () => {
    if (coreSetupComplete) return setScreen(DONE)
    const generation = setupGroups.find((group) => group.id === 'generation')
    if (!generation.complete) return setScreen(screenOf('image'))
    setScreen(screenOf('ollama'))
  }
  const openToolDetail = (id, origin) => {
    setDetailOrigin(origin)
    setScreen(screenOf(id))
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
    if (detailOrigin) {
      const destination = detailBackScreen(detailOrigin, DONE)
      setDetailOrigin(null)
      return setScreen(destination)
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
        const freshStep = deriveSetupSteps(fresh).find((x) => x.id === 'ollama')
        const reason = freshStep.setupComplete ? null : localVisionGateReason(freshStep)
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
        const ready = stepById[id].setupComplete
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
    <Link to="/datasets" onClick={() => writeSession(SETUP_REDIRECT_SESSION_KEY, '1')}
      className="text-xs text-content-subtle underline hover:text-content">
      Skip setup — I'll do it later
    </Link>
  )

  // --- Welcome + live machine scan --------------------------------------------
  if (kind === 'welcome') {
    // This page answers only whether setup has been completed. Runtime health lives
    // on the separate session-start page so stopping an app cannot undo setup.
    // Requirements apply to groups rather than every individual row: image providers
    // are alternatives, local vision powers automation, and the final two are extras.
    const triState = (reachable, complete) => reachable ? (complete ? 'ready' : 'partial') : 'missing'
    // The welcome page mirrors the actual wizard: one named row per step, in the
    // same order. This keeps the pre-flight promise in sync as steps are added.
    const scanRows = steps.map((step, index) => {
      if (step.id === 'image') {
        return { index, label: 'Cloud/API image provider', soft: true,
          stepId: step.id, state: step.providerConfigured ? 'ready' : 'missing', partial: '',
          readyText: 'set up' }
      }
      if (step.id === 'comfyui') {
        return { index, label: `Local image provider — ${step.installLabel}`, soft: true, stepId: step.id,
          state: step.setupComplete ? 'ready' : triState(step.dirValid, step.hasKlein),
          partial: 'found — finish the Klein model setup',
          readyText: 'set up' }
      }
      if (step.id === 'ollama') {
        const partial = step.reachable
          ? `running — load ${step.visionModel || 'a vision model'}`
          : step.provider === 'ollama' && step.installed ? 'installed — not running' : ''
        return { index, label: `Local vision — ${step.providerLabel}`, soft: false,
          stepId: step.id, state: step.setupComplete ? 'ready' : step.reachable
            ? (step.visionModelReady ? 'ready' : 'partial')
            : (step.installed ? 'partial' : 'missing'), partial,
          readyText: 'set up' }
      }
      if (step.id === 'quality') {
        return { index, label: 'Quality tools — ML extras', soft: true, stepId: step.id,
          state: step.setupComplete ? 'ready' : step.status === 'partial' ? 'partial' : 'missing',
          partial: 'some helpers installed', readyText: 'set up' }
      }
      return { index, label: 'LoRA training — ai-toolkit', soft: true, stepId: step.id,
        state: step.valid && !step.hfAccessConfigured ? 'partial'
          : step.setupComplete ? 'ready'
          : (detected?.aitoolkit?.dir ? 'partial' : 'missing'),
        partial: step.valid && !step.hfAccessConfigured
          ? 'core ready — gated model access missing'
          : 'found on disk — one click to use',
        readyText: 'core + gated access set up' }
    })
    const SCAN_META = {
      ready: { glyph: '✓', cls: 'text-emerald-400', word: 'ready' },
      partial: { glyph: '⚠', cls: 'text-amber-400', word: '' },
      missing: { glyph: '✗', cls: 'text-content-subtle', word: 'not found' },
    }
    const scanRowsById = Object.fromEntries(scanRows.map((row) => [row.stepId, row]))
    const NEUTRAL = { glyph: '○', cls: 'text-content-subtle' }
    const ScanRow = ({ row: r }) => {
      const soft = r.soft && r.state !== 'ready'
      const m = soft ? { ...SCAN_META[r.state], ...NEUTRAL } : SCAN_META[r.state]
      const word = r.state === 'ready' ? (r.readyText || 'set up')
        : r.state === 'partial' ? r.partial
        : r.state === 'missing' ? 'not configured'
        : m.word
      return (
        <li>
          <button type="button" disabled={detecting} onClick={() => openToolDetail(r.stepId, 'setup')}
            className="flex w-full items-center justify-between gap-3 rounded-md px-2 py-1.5 text-left text-sm
              transition-colors hover:bg-surface-raised focus:outline-none focus-visible:ring-2 focus-visible:ring-primary
              disabled:cursor-default disabled:hover:bg-transparent">
            <span className="flex items-center gap-2">
              <span aria-hidden="true" className={detecting ? 'text-content-subtle' : m.cls}>
                {detecting ? '…' : m.glyph}
              </span>
              <span className="w-16 shrink-0 text-[10px] font-medium uppercase tracking-wide text-content-subtle">
                Step {r.index + 1} of {TOTAL_TOOLS}
              </span>
              <span className={r.state === 'ready' ? 'text-content' : 'text-content-muted'}>{r.label}</span>
            </span>
            <span className="flex items-center gap-1.5">
              <span className={`truncate text-right font-mono text-xs ${detecting ? 'text-content-subtle' : m.cls}`}>
                {detecting ? '' : word}
              </span>
              {!detecting && <span aria-hidden="true" className="text-xs text-content-subtle">›</span>}
            </span>
          </button>
        </li>
      )
    }
    return (
      <div className="mx-auto max-w-2xl space-y-6">
        <div className="text-center">
          <div className="text-3xl" aria-hidden="true">🧬</div>
          <h1 className="mt-2 text-2xl font-bold text-content">Setup</h1>
          <p className="mt-2 text-sm text-content-muted">
            Configure each tool once. Whether local apps are running today is checked separately on the next page.
          </p>
        </div>

        <section className="rounded-xl border border-border bg-surface p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-content">
              {detecting ? 'Checking setup…' : 'Setup checklist'}
            </h2>
            {detecting
              ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-border-strong border-t-primary" aria-hidden="true" />
              : (
                <button type="button" onClick={() => runAutodetect(config)}
                  className="text-xs text-primary underline">Re-scan</button>
              )}
          </div>
          <div className="mt-4 space-y-5">
            {setupGroups.map((group) => (
              <section key={group.id} aria-labelledby={`setup-group-${group.id}`}>
                <div className="flex items-baseline justify-between gap-3 border-b border-border pb-1.5">
                  <h3 id={`setup-group-${group.id}`} className="text-sm font-semibold text-content">{group.title}</h3>
                  <span className={`text-[10px] font-medium uppercase tracking-wide ${group.required
                    ? 'text-primary' : 'text-content-subtle'}`}>
                    {group.id === 'generation' ? 'At least one required' : group.required ? 'Required for automation' : 'Optional'}
                  </span>
                </div>
                <p className="mt-1 text-xs text-content-subtle">{group.requirement}</p>
                <ul className="mt-1 space-y-1">
                  {group.stepIds.map((stepId) => <ScanRow key={stepId} row={scanRowsById[stepId]} />)}
                </ul>
              </section>
            ))}
          </div>
          {scanError && !detecting && (
            <div role="alert" className="mt-3 flex items-center justify-between gap-3 text-xs text-rose-400">
              <span>Machine scan failed: {scanError}</span>
              <button type="button" onClick={() => runAutodetect(config)} className="shrink-0 underline">Retry scan</button>
            </div>
          )}
          {scanned && !detecting && !scanError && (
            <p className="mt-3 text-xs text-content-subtle">
              {coreSetupComplete ? 'Main workflow setup is complete.' : 'Main workflow setup needs attention.'}{' '}
              {optionalConfiguredCount} of 2 optional enhancements configured.
            </p>
          )}
        </section>

        <div className="flex items-center justify-between">
          {skipLink}
          <button type="button" onClick={goNext}
            className="rounded-lg bg-gradient-primary px-5 py-2 text-sm font-semibold text-white">
            {coreSetupComplete ? 'Start this session →' : 'Start setup →'}
          </button>
        </div>
      </div>
    )
  }

  // --- Session readiness -------------------------------------------------------
  if (kind === 'done') {
    return (
      <div className="mx-auto max-w-2xl space-y-6">
        <div className="text-center">
          <div className="text-3xl" aria-hidden="true">▶</div>
          <h1 className="mt-2 text-2xl font-bold text-content">Start this session</h1>
          <p className="mt-1 text-sm text-content-muted">
            Setup is complete. Start only the local tools you plan to use today.
          </p>
        </div>
        <section className="rounded-xl border border-border bg-surface p-5">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-base font-semibold text-content">Is everything running?</h2>
            <button type="button" onClick={() => refresh(true)} disabled={capabilitiesLoading}
              className="text-xs text-primary underline disabled:cursor-wait disabled:text-content-subtle">
              {capabilitiesLoading ? 'Checking…' : 'Re-check'}
            </button>
          </div>
          <ul className="mt-3 space-y-1">
            {sessionRows.map((row) => (
              <li key={row.id}>
                <button type="button" onClick={() => {
                  setDetailOrigin('session')
                  setScreen(screenOf(row.id))
                }}
                  className="flex w-full items-center justify-between gap-3 rounded-md px-2 py-1.5 text-left text-sm
                    transition-colors hover:bg-surface-raised focus:outline-none focus-visible:ring-2 focus-visible:ring-primary">
                  <span className="flex items-center gap-2 text-content">
                    <span aria-hidden="true" className={row.ready ? 'text-emerald-400' : 'text-content-subtle'}>
                      {row.ready ? '✓' : '○'}
                    </span>
                    {row.label}
                  </span>
                  <span className={`flex items-center gap-1.5 font-mono text-xs ${row.ready ? 'text-emerald-400' : 'text-content-muted'}`}>
                    {row.status}<span aria-hidden="true" className="text-content-subtle">›</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-content-subtle">
            {sessionReadyCount} of {sessionRows.length} tools are usable now.
          </p>
          {capabilitiesError && (
            <p role="alert" className="mt-2 text-xs text-rose-400">Could not refresh runtime status.</p>
          )}
        </section>
        <div className="flex items-center justify-between">
          <button type="button" onClick={() => setScreen(0)} className="text-xs text-content-subtle underline hover:text-content">
            ← Back to setup
          </button>
          <Link to="/datasets" className="rounded-lg bg-gradient-primary px-5 py-2 text-sm font-semibold text-white">
            Open datasets →
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
        {detailOrigin === 'session' ? (
          <span className="text-xs font-medium uppercase tracking-wide text-primary">Session check</span>
        ) : <ProgressDots />}
        <span className="text-xs text-content-subtle">
          {detailOrigin === 'session' ? 'How to make this tool ready now' : `Step ${stepNo} of ${TOTAL_TOOLS}`}
        </span>
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
            setField={setField} persist={persist} applyDetectedPath={applyDetectedPath}
            mode={detailOrigin === 'session' ? 'session' : 'setup'} />
        </div>
      </section>

      {reason && (
        <p className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
          🔒 {reason}
        </p>
      )}
      <div className="flex items-center justify-between">
        <button type="button" onClick={goBack} className="text-xs text-content-subtle underline hover:text-content">
          {detailOrigin === 'session' ? '← Back to session status' : '← Back'}
        </button>
        {detailOrigin === 'session' ? (
          <button type="button" onClick={() => refresh(true)} disabled={capabilitiesLoading}
            className="rounded-lg bg-gradient-primary px-5 py-2 text-sm font-semibold text-white disabled:cursor-wait disabled:opacity-40">
            {capabilitiesLoading ? 'Checking…' : 'Re-check now'}
          </button>
        ) : (
          <div className="flex items-center gap-4">
            {skipLink}
            <button type="button" onClick={nextWithSave} disabled={advancing}
              title={reason || ''}
              className="rounded-lg bg-gradient-primary px-5 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40">
              {nextLabel}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
