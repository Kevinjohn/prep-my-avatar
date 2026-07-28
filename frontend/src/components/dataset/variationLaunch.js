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
