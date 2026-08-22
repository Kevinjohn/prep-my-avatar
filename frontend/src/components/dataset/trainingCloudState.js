// Shared suffix for the two families that never had a cloud lane built —
// kept as one string so the two messages below can't drift apart.
const LOCAL_ONLY_REASON_SUFFIX = ' trains locally only — the cloud lane covers Z-Image, Krea 2 and FLUX.2 Klein'

/** Derive legacy-compatible active runs and the single authoritative launch block reason. */
export function deriveCloudTrainingState({
  cloudStatus, datasetId, trainType, keptCount, preflightFloor, typeLabel,
  customBase, vaePath, tePath, hasInvalidStepsOverride, stepsOverrideValid,
  launchConfigReady,
}) {
  const actives = cloudStatus.actives || (cloudStatus.active ? [cloudStatus.active] : [])
  const activeHere = actives.find((run) => run.dataset_id === datasetId
    && (!run.train_type || run.train_type === trainType))
  const limit = cloudStatus.limit || 1
  let disabledReason = null
  if (trainType === 'sdxl') disabledReason = `SDXL${LOCAL_ONLY_REASON_SUFFIX}`
  else if (trainType === 'flux') disabledReason = `FLUX.1${LOCAL_ONLY_REASON_SUFFIX}`
  else if (customBase || (trainType === 'sdxl' && (vaePath || tePath))) disabledReason = 'Custom weights are local-only — cloud training uses the official Hugging Face bases'
  else if (hasInvalidStepsOverride || !stepsOverrideValid) disabledReason = 'Target steps must be a whole number of at least 500'
  else if (!launchConfigReady) disabledReason = 'Training configuration and readiness must load successfully before launch'
  else if (keptCount < preflightFloor) disabledReason = `Only ${keptCount} image(s) kept — the cloud minimum for ${typeLabel} is ${preflightFloor}`
  else if (activeHere) disabledReason = `A ${typeLabel} cloud run is already active on this dataset`
  else if (actives.length >= limit) disabledReason = `Cloud run limit reached (${actives.length}/${limit}) — stop one or raise the limit in Settings`
  return { actives, cloudActiveHere: activeHere, cloudDisabledReason: disabledReason }
}
