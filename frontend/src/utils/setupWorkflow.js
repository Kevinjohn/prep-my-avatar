export function ollamaGateReason(step) {
  if (!step || step.status === 'ready') return null
  if (!step.reachable) {
    if (!step.installed) return "Ollama isn't installed — download it and start it (port 11434) to continue."
    return 'Ollama is installed but not running — click ▶ Start Ollama below to continue.'
  }
  if (!step.visionModelReady) return 'Pull the vision model below to continue — Z-Image captioning needs it (JoyCaption only covers SDXL).'
  return 'Finish this step to continue.'
}

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
