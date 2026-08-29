export function resolveGeneratorSelection(stored, hadStored, configuredDefault, enabled) {
  const candidates = hadStored
    ? [stored, configuredDefault, ...(enabled || [])]
    : [configuredDefault, ...(enabled || [])]
  return candidates.find((candidate) => candidate && enabled?.includes(candidate)) || 'klein'
}
