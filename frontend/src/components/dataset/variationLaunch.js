export function buildVariationLaunch({ catalog, nsfwCatalog, customShots, selected, nsfwMode, isKlein }) {
  const map = (entry) => ({ id: entry.id, label: entry.label, prompt: entry.prompt,
    framing: entry.framing, ...(entry.nsfw ? { nsfw: true } : {}) })
  return [
    ...catalog.filter((entry) => selected.has(entry.id)).map(map),
    ...(nsfwMode && isKlein ? nsfwCatalog.filter((entry) => selected.has(entry.id))
      .map((entry) => map({ ...entry, nsfw: true })) : []),
    ...customShots.filter((entry) => selected.has(entry.id) && (isKlein || !entry.nsfw)).map(map),
  ]
}

export function partitionExistingShots(variations, doneByLabel) {
  return {
    existing: variations.filter((variation) => doneByLabel.get(variation.label)),
    fresh: variations.filter((variation) => !doneByLabel.get(variation.label)),
  }
}

/** Limit a remote engine to one output until the user keeps a likeness proof. */
export function applyRemoteIdentityCanary({ variations, multiplier, images, engine, isKlein }) {
  const requestedTotal = variations.length * multiplier
  if (isKlein) return { variations, multiplier, requestedTotal, canary: false }
  const approved = images.some((image) => (
    image.source === 'generated'
      && image.status === 'keep'
      && image.generation_engine === engine
  ))
  if (approved) return { variations, multiplier, requestedTotal, canary: false }
  return {
    variations: variations.slice(0, 1),
    multiplier: 1,
    requestedTotal,
    canary: true,
  }
}
