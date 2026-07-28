export const CONFIRMABLE_TRAINING_REFUSALS = [
  ['MISMATCH_CAPTION: ', 'allow_caption_mismatch'],
  ['UNCAPTIONED: ', 'allow_uncaptioned'],
  ['CUSTOM_WEIGHTS_UNVERIFIED: ', 'allow_unverified_weights'],
]

export function parseTrainingSteps(value) {
  const normalized = String(value || '').trim()
  const parsed = normalized && /^\d+$/.test(normalized) ? Number(normalized) : null
  const valid = parsed == null || (Number.isSafeInteger(parsed) && parsed >= 500)
  return { valid, invalidFormat: Boolean(normalized) && parsed == null, steps: valid ? parsed : null }
}

export function trainingLaunchBody(config, extra = {}) {
  return {
    ...extra, base_model: config.base, variant: config.variant,
    train_type: config.trainType, masked: config.masked, steps: config.steps,
    fresh: config.mode === 'fresh',
    ...(config.trainType === 'sdxl'
      ? { vae_path: config.vaePath, te_path: config.tePath } : {}),
  }
}

export function confirmableTrainingRefusal(error) {
  const text = String(error || '')
  const match = CONFIRMABLE_TRAINING_REFUSALS.find(([marker]) => text.includes(marker))
  return match ? { message: text.replace(match[0], ''), flag: match[1] } : null
}
