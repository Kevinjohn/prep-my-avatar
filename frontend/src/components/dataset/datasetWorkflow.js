const CHARACTER_ONLY = new Set(['anchors', 'coverage', 'reference', 'generate', 'score']);

export const DATASET_WORKFLOW_STEPS = Object.freeze([
  { slug: 'import', label: 'Import photos',
    description: 'Bring in the complete set of real photos you are allowed to use.' },
  { slug: 'review', label: 'Review corpus',
    description: 'Accept useful photos, reject weak ones, and record source rights.' },
  { slug: 'anchors', label: 'Choose anchors',
    description: 'Choose the clearest, most varied identity references for generation.' },
  { slug: 'coverage', label: 'Review coverage',
    description: 'Map what the accepted corpus covers and identify genuine gaps.' },
  { slug: 'reference', label: 'Set primary reference', optional: true,
    description: 'Optionally choose the main identity reference used by local tools.' },
  { slug: 'generate', label: 'Generate missing views', optional: true,
    description: 'Optionally generate only the views that the real-photo corpus lacks.' },
  { slug: 'curate', label: 'Curate images',
    description: 'Keep the strongest images, reject the rest, and resolve quality flags.' },
  { slug: 'captions', label: 'Caption images',
    description: 'Write accurate training captions for every kept image.' },
  { slug: 'score', label: 'Score face similarity', optional: true,
    description: 'Optionally compare each kept face with the primary reference.' },
  { slug: 'export', label: 'Export dataset',
    description: 'Download the kept images and captions in a training-ready ZIP.' },
  { slug: 'train', label: 'Train a LoRA', optional: true,
    description: 'Optionally train the prepared dataset locally or in the cloud.' },
  { slug: 'checkpoints', label: 'Review checkpoints', optional: true,
    description: 'Optionally inspect training checkpoints and choose candidates to test.' },
  { slug: 'studio', label: 'Test in Studio', optional: true,
    description: 'Optionally compare the trained LoRA with fixed prompts and seeds.' },
  { slug: 'backup', label: 'Back up dataset',
    description: 'Save a portable backup of the dataset and its preparation history.' },
]);

export function applicableDatasetSteps({ kind = 'character' } = {}) {
  if (kind === 'character') return [...DATASET_WORKFLOW_STEPS];
  return DATASET_WORKFLOW_STEPS.filter((step) => !CHARACTER_ONLY.has(step.slug));
}

export function resumeDatasetStep({ kind = 'character', completed = {} } = {}) {
  const steps = applicableDatasetSteps({ kind });
  return steps.find((step) => !step.optional && !completed[step.slug])
    || steps.find((step) => !completed[step.slug])
    || steps.at(-1);
}

/** @param {{requestedSlug?: string | null, kind?: string, completed?: Record<string, boolean>}} options */
export function resolveDatasetStep({ requestedSlug, kind = 'character', completed = {} } = {}) {
  const steps = applicableDatasetSteps({ kind });
  return steps.find((step) => step.slug === requestedSlug)
    || resumeDatasetStep({ kind, completed });
}

export function adjacentDatasetStep(currentSlug, direction, { kind = 'character' } = {}) {
  const steps = applicableDatasetSteps({ kind });
  const index = steps.findIndex((step) => step.slug === currentSlug);
  if (index < 0) return null;
  return steps[index + Math.sign(direction)] || null;
}

export function datasetWorkflowPath(datasetId, stepSlug = null) {
  const numericId = Number(datasetId);
  if (!Number.isInteger(numericId) || numericId <= 0) {
    throw new TypeError('A positive dataset id is required');
  }
  return `/datasets/${numericId}${stepSlug ? `/${stepSlug}` : ''}`;
}

const TARGET_STEPS = Object.freeze({
  'ds-add-import': 'import',
  'ds-add-scraper': 'import',
  'ds-corpus-review': 'review',
  'ds-coverage-plan': 'coverage',
  'gf-reference': 'reference',
  'ds-add-reference': 'reference',
  'gf-generate': 'generate',
  'ds-add-generate': 'generate',
  'gf-images': 'curate',
  'gf-curation': 'curate',
  'gf-captions': 'captions',
  'gf-export': 'export',
  'gf-training': 'train',
  'gf-checkpoints': 'checkpoints',
  'gf-studio': 'studio',
});

export function workflowStepForTarget(targetId) {
  return TARGET_STEPS[targetId] || 'curate';
}

const LEGACY_SECTION_DEFAULTS = Object.freeze({
  images: 'curate',
  add: 'import',
  curation: 'curate',
  captions: 'captions',
  export: 'export',
  training: 'train',
  checkpoints: 'checkpoints',
  studio: 'studio',
});

const LEGACY_PANEL_STEPS = Object.freeze({
  'add:import': 'import',
  'add:scraper': 'import',
  'add:corpus': 'review',
  'add:coverage': 'coverage',
  'add:reference': 'reference',
  'add:generate': 'generate',
  'curation:face-analysis': 'score',
  'curation:small-image-rescue': 'curate',
  'curation:watermarks': 'curate',
  'curation:review-flagged': 'curate',
  'curation:rejected-cleanup': 'curate',
  'captions:generate': 'captions',
  'captions:leak-review': 'captions',
  'captions:tools': 'captions',
  'export:training-zip': 'export',
  'export:hugging-face': 'export',
  'export:backup': 'backup',
  'training:launch': 'train',
  'training:advanced': 'train',
  'training:queue': 'train',
  'checkpoints:manager': 'checkpoints',
  'studio:launcher': 'studio',
});

export function legacyWorkspaceStep(searchParams) {
  const section = searchParams.get('section');
  const panel = searchParams.get('panel');
  return LEGACY_PANEL_STEPS[`${section}:${panel}`] || LEGACY_SECTION_DEFAULTS[section] || null;
}
