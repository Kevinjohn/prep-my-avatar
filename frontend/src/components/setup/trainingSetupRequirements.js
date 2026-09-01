export const TRAINING_FAMILY_REQUIREMENTS = [
  {
    id: 'zimage', label: 'Z-Image', needsHfToken: false, needsComfyCheckpoint: false,
    detail: 'The official base downloads without gated access. A custom single-file Z-Image base must be converted before training.',
    licenseLinks: [],
  },
  {
    id: 'sdxl', label: 'SDXL', needsHfToken: false, needsComfyCheckpoint: true,
    detail: 'Requires an SDXL checkpoint in the configured ComfyUI models/checkpoints folder, or a valid custom SDXL weights file.',
    licenseLinks: [],
  },
  {
    id: 'krea', label: 'Krea 2', needsHfToken: true, needsComfyCheckpoint: false,
    detail: 'Requires a current ai-toolkit with the krea2 architecture and access to the exact Raw or Turbo repository selected for the run.',
    licenseLinks: [
      { label: 'Krea 2 Raw', href: 'https://huggingface.co/krea/Krea-2-Raw' },
      { label: 'Krea 2 Turbo', href: 'https://huggingface.co/krea/Krea-2-Turbo' },
    ],
  },
  {
    id: 'flux', label: 'FLUX.1-dev', needsHfToken: true, needsComfyCheckpoint: false,
    detail: 'Requires access to the official gated FLUX.1-dev repository. At 1024, about 24 GB of accelerator memory is recommended; 768 is the lower-memory option.',
    licenseLinks: [
      { label: 'FLUX.1-dev', href: 'https://huggingface.co/black-forest-labs/FLUX.1-dev' },
    ],
  },
  {
    id: 'flux2klein', label: 'FLUX.2 Klein', needsHfToken: true, needsComfyCheckpoint: false,
    detail: 'Requires a current ai-toolkit with the flux2_klein architecture and access to the exact 4B or 9B training-base repository. Access to the separate ComfyUI fp8 repository does not establish training-base access.',
    licenseLinks: [
      { label: 'Klein base 4B', href: 'https://huggingface.co/black-forest-labs/FLUX.2-klein-base-4B' },
      { label: 'Klein base 9B', href: 'https://huggingface.co/black-forest-labs/FLUX.2-klein-base-9B' },
    ],
  },
];

export const TRAINING_LAUNCH_REQUIREMENTS = [
  { id: 'disk', label: 'Free disk', detail: 'At least 10 GB on both the training-output and immutable-dataset target drives.', kind: 'hard' },
  { id: 'active_run', label: 'Idle training slot', detail: 'No other owned local training process or GPU lease may be active.', kind: 'hard' },
  { id: 'toolkit_family', label: 'Family support', detail: 'Krea 2 and FLUX.2 Klein require their exact extension architectures in the installed ai-toolkit.', kind: 'hard' },
  { id: 'dataset_admission', label: 'Dataset admission', detail: 'Family image minimum, concept description, reconstruction choices, and strict-profile source rights are checked per dataset.', kind: 'hard' },
  { id: 'captions', label: 'Caption admission', detail: 'Missing captions or the wrong prose/booru style require an explicit confirmation before launch.', kind: 'confirm' },
  { id: 'custom_weights', label: 'Custom weights', detail: 'Files must exist and be readable; Z-Image single-file bases require conversion, and uncertain architectures require confirmation.', kind: 'hard' },
  { id: 'trigger_collision', label: 'Run-folder identity', detail: 'Two datasets cannot use the same trigger and base because their checkpoints would collide.', kind: 'hard' },
  { id: 'cloud_access', label: 'Cloud alternative', detail: 'Cloud training additionally requires a saved vast.ai key, funded account, and an offer within configured limits.', kind: 'hard' },
];
