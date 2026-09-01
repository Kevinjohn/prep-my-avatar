import {
  TRAINING_FAMILY_REQUIREMENTS,
  TRAINING_LAUNCH_REQUIREMENTS,
} from './trainingSetupRequirements';

function familyStatus(requirement, caps, hasHfToken) {
  if (!caps?.aitoolkit?.valid) return 'Core training engine unavailable';
  if (requirement.needsHfToken && !hasHfToken) return 'Hugging Face token required';
  if (requirement.needsComfyCheckpoint && !(caps?.comfyui?.models?.sdxl || []).length) {
    return 'SDXL checkpoint required';
  }
  if (requirement.needsHfToken) return 'Token saved · repository access checked on download';
  return 'Core prerequisite present';
}

export default function TrainingRequirementsPanel({ caps, hasHfToken }) {
  return (
    <section className="space-y-3 rounded-md border border-border bg-surface p-3"
      aria-labelledby="training-dependency-map">
      <div>
        <h2 id="training-dependency-map" className="text-sm font-semibold text-content">
          Complete training dependency map
        </h2>
        <p className="mt-1 text-xs text-content-muted">
          “ai-toolkit ready” covers only the core engine. Model access and run-specific admission are separate checks.
        </p>
      </div>

      <div className="divide-y divide-border rounded-md border border-border" role="list"
        aria-label="Requirements by training family">
        {TRAINING_FAMILY_REQUIREMENTS.map((requirement) => (
          <div key={requirement.id} role="listitem" className="space-y-1 px-3 py-2">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
              <h3 className="text-xs font-semibold text-content">{requirement.label}</h3>
              <span className="text-[0.6875rem] text-content-muted">
                {familyStatus(requirement, caps, hasHfToken)}
              </span>
            </div>
            <p className="text-[0.6875rem] leading-relaxed text-content-muted">{requirement.detail}</p>
            {!!requirement.licenseLinks.length && (
              <p className="flex flex-wrap gap-x-3 gap-y-1 text-[0.6875rem]">
                {requirement.licenseLinks.map((link) => (
                  <a key={link.href} href={link.href} target="_blank" rel="noreferrer"
                    className="text-primary underline">Accept {link.label} access →</a>
                ))}
              </p>
            )}
          </div>
        ))}
      </div>

      <div>
        <h3 className="text-xs font-semibold text-content">Checked for each launch</h3>
        <ul className="mt-1 space-y-1 text-[0.6875rem] text-content-muted">
          {TRAINING_LAUNCH_REQUIREMENTS.map((requirement) => (
            <li key={requirement.id} className="flex gap-2">
              <span className="w-14 shrink-0 font-medium uppercase tracking-wide text-content-subtle">
                {requirement.kind === 'confirm' ? 'Confirm' : 'Hard gate'}
              </span>
              <span><strong className="text-content">{requirement.label}:</strong> {requirement.detail}</span>
            </li>
          ))}
        </ul>
      </div>

      <p className="text-[0.6875rem] text-content-subtle">
        Optional masked training also needs the mask/ML extras; without them, the run must use unmasked training.
      </p>
    </section>
  );
}
