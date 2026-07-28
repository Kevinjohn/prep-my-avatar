/** Merge a server acknowledgement without overwriting edits made while saving. */
export function reconcileServerSnapshot(current, submitted, server) {
  if (JSON.stringify(current) === JSON.stringify(submitted)) return server
  if (!current || !submitted || !server || Array.isArray(current)
      || typeof current !== 'object' || typeof submitted !== 'object' || typeof server !== 'object') {
    return current
  }
  return Object.fromEntries(Object.keys(current).map((key) => [
    key,
    reconcileServerSnapshot(current[key], submitted[key], server[key]),
  ]))
}
