// Pure derivation of the guided Setup wizard state from live capabilities.
// No I/O — deterministic, so it is the single source of truth for card status.

export const SETUP_STEP_IDS = ['image', 'comfyui', 'ollama', 'quality', 'training']

// Tool reachable + its extra piece present -> ready; reachable only -> partial.
function gateStatus(reachable, complete) {
  if (reachable && complete) return 'ready'
  if (reachable) return 'partial'
  return 'available'
}

function imageStep(caps) {
  const e = caps.engines || {}
  const providerConfigured = !!(e.nanobanana || e.chatgpt)
  const ready = e.nanobanana || e.chatgpt || e.klein
  return {
    id: 'image', title: 'Image generation', recommended: true,
    unlocks: ['Nano Banana (Google or Replicate)', 'ChatGPT (gpt-image-2)', 'Klein (local)'],
    status: ready ? 'ready' : 'available', setupComplete: !!ready, runtimeReady: !!ready,
    providerConfigured,
    engines: { nanobanana: !!e.nanobanana, chatgpt: !!e.chatgpt, klein: !!e.klein },
  }
}

function comfyuiStep(caps) {
  const c = caps.comfyui || {}
  const app = c.app || {}
  const folderLauncher = c.folder_launcher || {}
  const installType = c.install_type || (folderLauncher.managed_by_desktop ? 'desktop' : '')
  const installLabel = installType === 'desktop' ? 'ComfyUI Desktop'
    : installType === 'git' ? 'ComfyUI from Git / code' : 'ComfyUI'
  const hasKlein = !!(c.models && c.models.klein && c.models.klein.length)
  const status = gateStatus(c.reachable, hasKlein)
  return {
    id: 'comfyui', title: `${installLabel} — local generation & Test Studio`, recommended: false,
    installType, installLabel,
    unlocks: ['Klein engine', 'Test Studio'],
    status, reachable: !!c.reachable, hasKlein, apiUrl: c.api_url || '',
    setupComplete: !!c.dir_valid && hasKlein,
    runtimeReady: !!c.reachable && hasKlein,
    // Whether comfyui.base_dir actually points at a ComfyUI install (main.py + models/):
    // a wrong/portable-wrapper path scans an empty models/ and finds no checkpoints.
    // baseDir = the path this verdict was PROBED against — the UI must not show the
    // verdict for a freshly typed (unsaved) path, it would judge the wrong string.
    dirConfigured: !!c.dir_configured, dirValid: !!c.dir_valid, resolvedDir: c.resolved_dir || '',
    baseDir: c.base_dir || '',
    folderLauncher: {
      cwd: folderLauncher.cwd || '', command: folderLauncher.command || '',
      managedByDesktop: !!folderLauncher.managed_by_desktop,
    },
    app: {
      name: app.name || '', path: app.path || '', bundleId: app.bundle_id || '',
      launchCommand: app.launch_command || '',
    },
  }
}

function ollamaStep(caps) {
  const o = caps.ollama || {}
  const local = caps.local_vision || {
    provider: 'ollama', label: 'Ollama', reachable: o.reachable,
    model_ready: o.vision_model_ready, url: o.url, vision_model: o.vision_model,
  }
  const status = gateStatus(local.reachable, local.model_ready)
  return {
    // Keep the historical id so saved wizard navigation remains compatible.
    id: 'ollama', title: 'Local vision — Ollama, LM Studio, or llama.cpp', recommended: false,
    unlocks: ['Captioning', 'Auto-classify framing', 'Auto head-crop'],
    status, provider: local.provider || 'ollama', providerLabel: local.label || 'Ollama',
    reachable: !!local.reachable, visionModelReady: !!local.model_ready,
    setupComplete: !!local.url && !!local.vision_model,
    runtimeReady: !!local.reachable && !!local.model_ready,
    url: local.url || '', visionModel: local.vision_model || '',
    // Execution-independent install signal (binary on disk) vs `reachable` (server
    // answering): installed && !reachable -> "installed but stopped", offer a Start.
    installed: local.provider === 'ollama' && !!o.installed, binaryPath: o.binary_path || '',
  }
}

function qualityStep(caps) {
  // Three scoped ML capabilities now (face scoring, masks, watermark inpainting) —
  // each installs/repairs on its own. The step is ready only when all three are in.
  const parts = [!!caps.face_scoring, !!caps.masks, !!caps.watermark_inpaint]
  const ready = parts.every(Boolean)
  const partial = parts.some(Boolean)
  return {
    id: 'quality', title: 'Quality tools (ML extras)', recommended: false,
    unlocks: ['Face-similarity scoring', 'Person masks', 'Watermark inpainting'],
    status: ready ? 'ready' : (partial ? 'partial' : 'available'),
    setupComplete: ready, runtimeReady: ready,
    faceScoring: !!caps.face_scoring, masks: !!caps.masks,
    watermarkInpaint: !!caps.watermark_inpaint,
  }
}

function trainingStep(caps) {
  const a = caps.aitoolkit || {}
  const hfAccessConfigured = !!caps.hf_publish
  return {
    id: 'training', title: 'LoRA training — ai-toolkit', recommended: false,
    unlocks: ['LoRA training', 'JoyCaption captioning (bonus)'],
    // A valid environment means the core engine is usable, not that every
    // family is launchable. Keep gated-family access visibly incomplete until
    // a token is saved; public/local families remain documented in the detail.
    status: a.valid ? (hfAccessConfigured ? 'ready' : 'partial') : 'available',
    setupComplete: !!a.configured, runtimeReady: !!a.valid,
    valid: !!a.valid, hfAccessConfigured,
  }
}

export function deriveSetupSteps(caps) {
  const c = caps || {}
  return [imageStep(c), comfyuiStep(c), ollamaStep(c), qualityStep(c), trainingStep(c)]
}

// Session readiness mirrors the five setup tool groups. It deliberately does not
// expand them into the ten downstream capabilities, which made the Setup flow
// impossible to reconcile with the five visible steps.
export function deriveSessionStatus(steps) {
  return (steps || []).map((step) => {
    if (step.id === 'comfyui' || step.id === 'ollama') {
      return { id: step.id, label: step.id === 'comfyui' ? step.installLabel : step.providerLabel,
        ready: !!step.runtimeReady, status: step.runtimeReady ? 'running' : 'not running' }
    }
    if (step.id === 'training') {
      return { id: step.id, label: 'ai-toolkit', ready: !!step.runtimeReady,
        status: step.runtimeReady ? 'ready' : step.setupComplete ? 'environment missing' : 'not configured' }
    }
    return { id: step.id, label: step.id === 'image' ? 'Image generation' : 'Quality tools',
      ready: !!step.runtimeReady, status: step.runtimeReady ? 'ready' : 'not ready' }
  })
}

export function deriveSetupGroups(steps) {
  const byId = Object.fromEntries((steps || []).map((step) => [step.id, step]))
  const generationComplete = !!(byId.image?.providerConfigured || byId.comfyui?.setupComplete)
  return [
    { id: 'generation', title: 'Image generation', requirement: 'Choose at least one provider',
      required: true, complete: generationComplete, stepIds: ['image', 'comfyui'] },
    { id: 'automation', title: 'Workflow automation',
      requirement: 'Required for automatic captioning and framing', required: true,
      complete: !!byId.ollama?.setupComplete, stepIds: ['ollama'] },
    { id: 'extras', title: 'Optional enhancements', requirement: 'Install only what you need',
      required: false, complete: null, stepIds: ['quality', 'training'] },
  ]
}

// The user's live capability checklist (Summary card). Watermark inpainting is a
// distinct ML runtime (Torch/Pillow/OpenCV) — an existing install that never added
// it must SEE it as still missing here, not be told "everything's ready".
export function deriveCapabilitySummary(caps) {
  const c = caps || {}
  const e = c.engines || {}
  const o = c.local_vision || c.ollama || {}
  const cap = c.captioners || {}
  return [
    { label: 'Nano Banana (Google or Replicate)', ok: !!e.nanobanana },
    { label: 'ChatGPT (gpt-image-2)', ok: !!e.chatgpt },
    { label: 'Klein (local)', ok: !!e.klein },
    { label: 'Captioning', ok: !!(cap.joycaption || cap.local_vision || cap.ollama) },
    { label: 'Auto-framing & head-crop', ok: !!(o.reachable && (o.model_ready ?? o.vision_model_ready)) },
    { label: 'Face-similarity scoring', ok: !!c.face_scoring },
    { label: 'Person masks', ok: !!c.masks },
    { label: 'Watermark inpainting', ok: !!c.watermark_inpaint },
    { label: 'LoRA training', ok: !!c.training_visible },
    { label: 'Test Studio', ok: !!c.studio_visible },
  ]
}

export function recommendedMet(caps) {
  const e = (caps && caps.engines) || {}
  return !!(e.nanobanana || e.chatgpt || e.klein)
}
