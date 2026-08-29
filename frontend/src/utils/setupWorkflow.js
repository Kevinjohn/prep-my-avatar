export function localVisionGateReason(step) {
  if (!step || step.status === 'ready') return null
  const provider = step.provider || 'ollama'
  const label = step.providerLabel || 'Ollama'
  if (!step.reachable) {
    if (provider === 'ollama' && step.installed) {
      return 'Ollama is installed but not running — click ▶ Start Ollama below to continue.'
    }
    if (provider === 'ollama') {
      return "Ollama isn't installed — download it and start it (port 11434) to continue."
    }
    return `${label} is not reachable at the configured URL — start its local server to continue.`
  }
  if (!step.visionModelReady) {
    return provider === 'ollama'
      ? 'Pull the vision model below to continue — Z-Image captioning needs it (JoyCaption only covers SDXL).'
      : `Load the configured vision model in ${label} to continue.`
  }
  return 'Finish this step to continue.'
}

// Backward-compatible export for older tests/imports.
export const ollamaGateReason = localVisionGateReason

/** Pure wizard navigation model; rendering and persistence stay outside it. */
export function setupNavigation(stepIds, stepById, screen) {
  const screens = ['welcome', ...stepIds, 'done']
  const kind = screens[screen]
  const done = screens.length - 1
  const isReady = (id) => stepById[id]?.status === 'ready'
  const toolIndex = (id) => stepIds.indexOf(id)
  const screenOf = (id) => stepIds.indexOf(id) + 1
  const find = (start, direction) => {
    for (let index = start + direction; index >= 0 && index < stepIds.length; index += direction) {
      if (!isReady(stepIds[index])) return stepIds[index]
    }
    return null
  }
  return {
    kind, done, isReady, toolIndex, screenOf,
    allReady: stepIds.every(isReady),
    firstUnfinished: stepIds.find((id) => !isReady(id)) || null,
    nextUnfinished: (from) => find(from, 1),
    previousUnfinished: (from) => find(from, -1),
  }
}
