const isPlainObject = (value) => (
  value !== null && typeof value === 'object' && !Array.isArray(value)
)

/**
 * Return the smallest nested config object that changes `saved` into `draft`.
 * The settings API deep-merges this patch, so an older tab cannot overwrite
 * unrelated fields that another tab saved after this draft was loaded.
 */
export function buildSettingsPatch(saved, draft) {
  if (Object.is(saved, draft)) return undefined
  if (!isPlainObject(saved) || !isPlainObject(draft)) {
    return JSON.stringify(saved) === JSON.stringify(draft) ? undefined : draft
  }

  const patch = {}
  for (const [key, value] of Object.entries(draft)) {
    const changed = buildSettingsPatch(saved[key], value)
    if (changed !== undefined) patch[key] = changed
  }
  return Object.keys(patch).length ? patch : undefined
}
