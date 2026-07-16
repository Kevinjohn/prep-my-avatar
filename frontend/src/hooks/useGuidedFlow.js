import { useMemo } from 'react';
import { buildSmallImageRescuePairs } from '../utils/smallImageRescue.js';
import { buildImageImprovementPairs } from '../utils/imageImprovement.js';

/* Pure derivation of the guided path from the dataset payload + capabilities.
   No fetching here — lives at the workspace's existing poll rhythm. */
export function deriveSteps(d, caps, checkpointCount = 0) {
  const images = (d && d.images) || [];
  const live = images.filter((i) => i.status !== 'failed');
  const unresolvedPairs = [
    ...buildSmallImageRescuePairs(images).filter((pair) => !pair.resolved),
    ...buildImageImprovementPairs(images).filter((pair) => !pair.resolved),
  ];
  const exclusiveIds = new Set(unresolvedPairs.flatMap((pair) => (
    pair.imageIds || [pair.original.id, pair.candidate.id]
  )));
  const ordinary = live.filter((image) => !exclusiveIds.has(image.id));
  const kept = ordinary.filter((i) => i.status === 'keep');
  const imported = live.filter((i) => i.source === 'import' && i.filename
    && !['klein_image_improve', 'klein_small_image'].includes(i.derivation_kind));
  const generated = ordinary.filter((i) => i.source === 'generated' && i.filename);
  const triage = ordinary.filter((i) => i.status === 'pending' && i.filename);
  const generating = ordinary.filter((i) => i.status === 'pending' && !i.filename);
  const captioned = kept.filter((i) => (i.caption || '').trim());
  const scored = kept.filter((i) => i.face_state);
  const trainMode = !!(caps && caps.training_visible);
  const hasImportedCorpus = imported.length > 0;
  const coveragePlan = d && d.coverage_plan;
  const hasCoveragePlan = !!coveragePlan?.available;
  const unclassified = coveragePlan?.summary?.unclassified || 0;
  const recommended = coveragePlan?.recommended_variation_ids || [];
  const anchorPlan = d && d.anchor_plan;
  const visionReady = !!(caps?.ollama?.reachable && caps?.ollama?.vision_model_ready);

  const steps = [
    { id: 'corpus', label: 'Import corpus', targetId: 'ds-add-import',
      done: hasImportedCorpus, optional: !!(d && d.ref_filename),
      subtitle: hasImportedCorpus ? `${imported.length} imported` : 'real photos first' },
    { id: 'review', label: 'Review corpus', targetId: 'ds-corpus-review',
      done: hasImportedCorpus && unclassified === 0,
      optional: !hasImportedCorpus || !visionReady,
      subtitle: unclassified ? `${unclassified} need coverage` : hasImportedCorpus ? 'mapped' : 'after import' },
    { id: 'anchors', label: 'Choose anchors', targetId: 'ds-corpus-review',
      done: !!anchorPlan?.selected_total, optional: !hasImportedCorpus,
      subtitle: anchorPlan?.selected_total ? `${anchorPlan.selected_total}/${anchorPlan.limit} selected` : 'automatic or pinned' },
    { id: 'coverage', label: 'Plan coverage', targetId: 'ds-coverage-plan',
      done: hasImportedCorpus && hasCoveragePlan, optional: !hasImportedCorpus,
      subtitle: hasCoveragePlan ? `${coveragePlan.summary?.gaps || 0} framing gaps` : 'automatic' },
    { id: 'reference', label: 'Primary reference', targetId: 'gf-reference',
      done: !!(d && d.ref_filename), optional: true,
      subtitle: d && d.ref_filename ? 'set' : 'optional fallback; Klein only' },
    { id: 'generate', label: hasImportedCorpus ? 'Generate gaps' : 'Generate', targetId: 'gf-generate',
      done: generated.length > 0 || (hasImportedCorpus && recommended.length === 0),
      optional: hasImportedCorpus,
      subtitle: recommended.length ? `${recommended.length} suggested` : 'no proven gaps', busy: generating.length > 0 },
    { id: 'curate', label: 'Curate', targetId: unresolvedPairs.length ? 'gf-curation' : 'gf-images',
      done: live.length > 0 && triage.length === 0 && unresolvedPairs.length === 0 && kept.length > 0,
      subtitle: unresolvedPairs.length ? `${unresolvedPairs.length} comparison(s) to review`
        : triage.length ? `${triage.length} to triage` : `${kept.length} kept` },
    { id: 'caption', label: 'Caption', targetId: 'gf-captions',
      done: kept.length > 0 && captioned.length === kept.length,
      subtitle: `${captioned.length}/${kept.length} captioned` },
  ];
  if (caps && caps.face_scoring) {
    steps.push({ id: 'score', label: 'Score', targetId: 'gf-curation', optional: true,
      done: kept.length > 0 && scored.length === kept.length, subtitle: 'optional' });
  }
  steps.push(trainMode
    ? { id: 'finish', label: 'Train', targetId: 'gf-training',
        done: checkpointCount > 0, subtitle: checkpointCount ? `${checkpointCount} checkpoint(s)` : '' }
    : { id: 'finish', label: 'Export', targetId: 'gf-export', done: false, subtitle: 'ZIP',
        unavailable: false });
  if (trainMode) steps.push({ id: 'checkpoints', label: 'Checkpoints & LoRAs', targetId: 'gf-checkpoints',
    done: checkpointCount > 0,
    subtitle: checkpointCount ? `${checkpointCount} available` : 'after training' });
  steps.push({ id: 'studio', label: 'Studio', targetId: 'gf-studio',
    done: !!(d && d.best_settings),
    unavailable: !(caps && caps.studio_visible),
    hint: caps && caps.studio_visible ? '' : 'Configure ComfyUI in Settings' });

  const nextStep = steps.find((s) => !s.done && !s.optional && !s.unavailable) || null;
  return { steps, nextStep };
}

export default function useGuidedFlow(d, caps, checkpointCount = 0) {
  return useMemo(() => deriveSteps(d, caps, checkpointCount), [d, caps, checkpointCount]);
}
