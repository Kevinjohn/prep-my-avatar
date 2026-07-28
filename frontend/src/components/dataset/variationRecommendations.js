export function initialVariationSelection(presets, bodyFidelity, recommendedIds) {
  if (Array.isArray(recommendedIds)) return recommendedIds;
  const fallback = bodyFidelity
    ? (presets?.body_emphasis || presets?.balanced_25)
    : presets?.balanced_25;
  return fallback || [];
}
