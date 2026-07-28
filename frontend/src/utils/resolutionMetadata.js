export function tierDims(metadata, aspectRatio, tier, maxLongSide) {
  const profile = maxLongSide && maxLongSide <= 1024 ? 'sdxl' : 'default'
  return metadata?.dimensions?.[profile]?.[aspectRatio]?.[tier]
    || metadata?.dimensions?.[profile]?.square?.[tier]
    || [0, 0]
}
