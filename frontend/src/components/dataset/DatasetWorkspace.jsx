import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import CompositionBar from './CompositionBar';
import CoveragePlan from './CoveragePlan';
import CorpusWorkbench from './CorpusWorkbench';
import ReferencePanel from './ReferencePanel';
import VariationCatalog from './VariationCatalog';
import TrainingPanel from './TrainingPanel';
import { fmt } from '../../utils/studioFormat';
import ImportDropzone from './ImportDropzone';
import ConceptSourcesPanel from './ConceptSourcesPanel';
import { isScraperImportBlocked } from './scraperState';
import DatasetGrid from './DatasetGrid';
import SmallImageRescueReview from './SmallImageRescueReview';
import ImageImprovementReview from './ImageImprovementReview';
import CurationHistory from './CurationHistory';
import CaptionToolsBar from './CaptionToolsBar';
import { recaptionConfirmation } from './captionCategory';
import { captionRewriteCounts } from '../../utils/captionOrigin';
import CropModal from './CropModal';
import DatasetLightbox from './DatasetLightbox';
import DatasetSettingsModal from './DatasetSettingsModal';
import PublishHfModal from './PublishHfModal';
import WatermarkReviewLightbox from './WatermarkReviewLightbox';
import { datasetImageUrl } from './datasetImageUrl';
import { useToast } from '../common/Toast';
import { useConfirmDialog, usePromptDialog } from '../common/ConfirmDialog';
import { useCapabilities } from '../../context/CapabilitiesContext';
import InstallRunner from '../setup/InstallRunner';
import DatasetWorkflowNav, { DatasetStepActions } from './DatasetWorkflowNav';
import TrainingReadiness from './TrainingReadiness';
import useGuidedFlow from '../../hooks/useGuidedFlow';
import { deriveSetupSteps } from '../../hooks/useSetupSteps';
import { localVisionGateReason } from '../../utils/setupWorkflow';
import { filterImages, normalizeTag } from '../../utils/tagFilter';
import { EXTERNAL_VISION_PROVIDERS, externalVisionWarning } from '../../utils/externalVision';
import {
  buildSmallImageRescuePairs,
  filterSmallImageRescueGrid,
  isSmallImageRescueRow,
} from '../../utils/smallImageRescue';
import { buildImageImprovementPairs, filterImageImprovementGrid } from '../../utils/imageImprovement';
import {
  adjacentDatasetStep,
  applicableDatasetSteps,
  resolveDatasetStep,
  workflowStepForTarget,
} from './datasetWorkflow';
import { GridFilterBar } from './WorkspaceChrome';

const EMPTY_IMAGES = Object.freeze([]);
const NOOP = () => {};

// Style partagé des items du menu « ⋯ More » du header (actions secondaires).
const MENU_ITEM = 'w-full flex items-center gap-2 text-left px-2.5 py-1.5 rounded-md text-sm text-content hover:bg-surface-raised disabled:opacity-40';

// Flash the block the user was just sent to (gf-highlight, index.css) so the eye
// finds it. The remove + forced reflow restarts the animation when the same
// destination is chosen twice in a row. Both jump paths — the checklist's "Fix →"
// and the URL-driven reveal — land the same way, so they flash the same way.
// The " 12/64" suffix a running pass adds to its label. `kind` narrows it to one
// pass, for buttons that only speak for themselves; the activity banner names
// whatever is running and so passes none. A pass with no total shows no suffix.
function activityProgress(activity, kind = null) {
  if (!activity || (kind && activity.kind !== kind) || !activity.total) return '';
  return ` ${activity.done}/${activity.total}`;
}

export default function DatasetWorkspace({ ds, onBack, stepSlug, onStepChange }) {
  const navigate = useNavigate();
  const toast = useToast();
  const confirm = useConfirmDialog();
  const promptDialog = usePromptDialog();
  const { caps, refresh: refreshCaps } = useCapabilities();
  const d = ds.data;
  const [cropImg, setCropImg] = useState(null);
  // Frozen snapshot of the flagged queue when review mode opens (null = closed).
  const [reviewQueue, setReviewQueue] = useState(null);
  const zipInput = useRef(null);   // hidden input for "Import dataset (ZIP)"
  const [refCrop, setRefCrop] = useState(false);
  const [viewImg, setViewImg] = useState(null);
  const [captionMode, setCaptionMode] = useState(null);   // null → défaut auto selon train_type
  const [captionProvider, setCaptionProvider] = useState('configured');
  const [classificationProvider, setClassificationProvider] = useState('configured');
  const [replaceAsserted, setReplaceAsserted] = useState(false);
  const [showLeaks, setShowLeaks] = useState(false);       // liste dépliée des captions qui fuient
  const [scraperOpen, setScraperOpen] = useState(false);
  const [captionToolsOpen, setCaptionToolsOpen] = useState(false);
  const [installInpaintOpen, setInstallInpaintOpen] = useState(false);  // panneau d'install LaMa
  const [checkpointCount, setCheckpointCount] = useState(0);
  const [checkpointHost, setCheckpointHost] = useState(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [publishHfOpen, setPublishHfOpen] = useState(false);
  const [sessionCompletedSteps, setSessionCompletedSteps] = useState(
    /** @type {Record<string, boolean>} */ ({}),
  );
  // Grid tag-filter (session-only): tags whose images are hidden (exclude) or the
  // ONLY tags allowed through (include). Both are normalized (trim+lowercase).
  const [excludeTags, setExcludeTags] = useState([]);
  const [includeTags, setIncludeTags] = useState([]);
  const images = d?.images || EMPTY_IMAGES;
  const { steps: guidedSteps } = useGuidedFlow(d, caps, checkpointCount);
  const guidedById = useMemo(
    () => Object.fromEntries(guidedSteps.map((step) => [step.id, step])),
    [guidedSteps],
  );
  const importedForProgress = images.filter((image) => image.source === 'import' && image.filename);
  const completedSteps = {
    import: Boolean(guidedById.corpus?.done),
    review: importedForProgress.length > 0
      && importedForProgress.every((image) => image.status !== 'pending'),
    anchors: Boolean(guidedById.anchors?.done),
    coverage: Boolean(d?.coverage_plan?.available)
      && Number(d?.coverage_plan?.summary?.unclassified || 0) === 0,
    reference: Boolean(guidedById.reference?.done),
    generate: images.some((image) => image.source === 'generated' && image.filename),
    curate: Boolean(guidedById.curate?.done),
    captions: Boolean(guidedById.caption?.done),
    score: Boolean(guidedById.score?.done),
    export: Boolean(sessionCompletedSteps.export),
    train: checkpointCount > 0,
    checkpoints: checkpointCount > 0,
    studio: Boolean(d?.best_settings),
    backup: Boolean(sessionCompletedSteps.backup),
  };
  const activeStep = resolveDatasetStep({
    requestedSlug: stepSlug,
    kind: d?.kind || 'character',
    completed: completedSteps,
  });
  const localVisionStep = deriveSetupSteps(caps).find((step) => step.id === 'ollama');
  const workflowSteps = applicableDatasetSteps({ kind: d?.kind || 'character' }).map((step) => {
    const unavailableReason = step.slug === 'score' && !caps.face_scoring
      ? 'Configure face scoring in Setup'
      : (step.slug === 'train' || step.slug === 'checkpoints') && !caps.training_visible
        ? 'Configure training in Setup'
        : step.slug === 'studio' && !caps.studio_visible
          ? 'Configure ComfyUI in Setup'
          : '';
    return { ...step, done: Boolean(completedSteps[step.slug]),
      unavailable: Boolean(unavailableReason), unavailableReason };
  });
  const previousWorkflowStep = adjacentDatasetStep(activeStep.slug, -1, { kind: d?.kind });
  const nextWorkflowStep = adjacentDatasetStep(activeStep.slug, 1, { kind: d?.kind });

  useEffect(() => {
    if (d && stepSlug !== activeStep.slug) onStepChange(activeStep.slug, { replace: true });
  }, [d, stepSlug, activeStep.slug, onStepChange]);
  useEffect(() => {
    setSessionCompletedSteps({});
  }, [d?.id]);
  useEffect(() => {
    if (!d?.id) return;
    const frame = requestAnimationFrame(() => {
      document.getElementById('dataset-step-heading')?.focus({ preventScroll: true });
      window.scrollTo({ top: 0, behavior: 'auto' });
    });
    return () => cancelAnimationFrame(frame);
  }, [d?.id, activeStep.slug]);
  const recaptionCounts = useMemo(() => captionRewriteCounts(images), [images]);
  useEffect(() => {
    setReplaceAsserted(false);
  }, [d?.id]);
  useEffect(() => {
    if (!recaptionCounts.asserted) setReplaceAsserted(false);
  }, [recaptionCounts.asserted]);
  const curationHistoryKey = useMemo(() => images.map((image) => [
    image.id, image.status, image.caption || '', image.caption_origin || '',
    image.anchor_decision || '',
    image.framing || '', JSON.stringify(image.coverage || {}),
    JSON.stringify(image.coverage_provenance || {}),
    JSON.stringify(image.source_rights || {}),
  ].join(':')).join('|'), [images]);
  const section = ['curate', 'score'].includes(activeStep.slug) ? 'curation'
    : activeStep.slug === 'captions' ? 'captions'
      : activeStep.slug === 'train' ? 'training'
        : activeStep.slug;

  // The everyday image grid stays genuinely paginated. The two review surfaces
  // that need cross-image relationships (exclusive reconstruction pairs and
  // caption leak editing) explicitly hydrate the remaining pages on entry.
  const {
    hasMoreImages, loadingMoreImages, loadAllImages, imageHydrationError,
  } = ds;
  const reviewNeedsHydration = (section === 'curation' || section === 'captions')
    && (hasMoreImages || loadingMoreImages);
  useEffect(() => {
    if ((section === 'curation' || section === 'captions')
        && hasMoreImages && !loadingMoreImages && !imageHydrationError) {
      loadAllImages();
    }
  }, [section, hasMoreImages, loadingMoreImages, imageHydrationError, loadAllImages]);

  const onRevealOpenChange = useCallback((_panelId, nextOpen, setter) => {
    setter(nextOpen);
  }, []);
  // Filters are per-dataset & transient — drop them when switching datasets so they
  // never leak from one dataset to the next.
  useEffect(() => { setExcludeTags([]); setIncludeTags([]); }, [d?.id]);


  // Every value here is a pure function of `images`, and every one of them is an
  // array or a Set — a fresh identity on each render, handed to memoised children
  // and to their own useMemos downstream. Deriving them once per image list is
  // what makes those memos hit; computing them inline meant none of them ever did.
  // Declared above the early return because it is a hook.
  const pairs = useMemo(() => {
    const rescue = buildSmallImageRescuePairs(images);
    const unresolvedRescue = rescue.filter((pair) => !pair.resolved);
    const improvement = buildImageImprovementPairs(images);
    const unresolvedImprovement = improvement.filter((pair) => !pair.resolved);
    // An unresolved pair is intentionally absent from the generic grid/bulk
    // controls: only the atomic side-by-side resolver may decide it. Once resolved,
    // the chosen keep + rejected counterpart return to the regular dataset view.
    const unresolvedRescueIds = new Set(unresolvedRescue.flatMap(
      (pair) => [pair.original.id, pair.candidate.id],
    ));
    const unresolvedImprovementIds = new Set(unresolvedImprovement.flatMap(
      (pair) => pair.imageIds,
    ));
    const rescueGridImages = filterSmallImageRescueGrid(images);
    return {
      unresolvedRescuePairs: unresolvedRescue,
      unresolvedRescueIds,
      rescuePairIds: new Set(rescue.flatMap((pair) => [pair.original.id, pair.candidate.id])),
      unresolvedImprovementPairs: unresolvedImprovement,
      improvementPairIds: new Set(improvement.flatMap((pair) => pair.imageIds)),
      unresolvedImprovementIds,
      unresolvedExclusiveIds: new Set([...unresolvedRescueIds, ...unresolvedImprovementIds]),
      reviewGridImages: filterImageImprovementGrid(rescueGridImages),
    };
  }, [images]);

  if (!d) return <p className="text-content-subtle text-sm">Loading…</p>;

  const {
    unresolvedRescuePairs, unresolvedRescueIds, rescuePairIds, unresolvedImprovementPairs,
    improvementPairIds, unresolvedImprovementIds, unresolvedExclusiveIds, reviewGridImages,
  } = pairs;
  const rescueReviewCount = unresolvedRescuePairs.length;
  // A CONCEPT dataset hides everything to do with identity/faces (reference, the
  // variation generator, face analysis, the leak badge, composition, the guided
  // flow) — what is left is raw import → curation → caption (inverted) → training.
  // 'style' follows the same UI path as concept: no reference/face/composition,
  // just raw import → curation → caption (content only, optional) → training.
  const concept = d.kind === 'concept' || d.kind === 'style';
  // Leak check is KIND-specific (see the caption-leak panel): character flags identity,
  // concept flags the caption NAMING the concept (must bind to the trigger), style never
  // (its subjects' description IS the content). `concept` above stays "concept OR style"
  // for the shared layout gating.
  const isConcept = d.kind === 'concept';
  const isStyle = d.kind === 'style';
  // Fidélité corps : captions bannissent aussi les marques corporelles, composition
  // cible plus de bustes/corps, import plein cadre par défaut.
  const bodyFid = d.fidelity === 'body';
  const summary = d.image_summary || {};
  const totalImages = summary.total ?? images.length;
  const kept = summary.kept ?? images.filter((i) => i.status === 'keep').length;
  const unused = summary.unused ?? images.filter(
    (i) => (i.status === 'reject' || i.status === 'failed')
      && !rescuePairIds.has(i.id) && !improvementPairIds.has(i.id),
  ).length;
  const keptCaptioned = summary.kept_captioned
    ?? images.filter((i) => i.status === 'keep' && Boolean((i.caption || '').trim())).length;
  const keptUncaptioned = kept - keptCaptioned;
  const faceReviewImages = images.filter(
    (image) => image.status === 'keep' && image.filename,
  );
  const faceScored = faceReviewImages.filter(
    (image) => image.face_state === 'scorable' && Number.isFinite(image.face_score),
  ).length;
  const faceNotScorable = faceReviewImages.filter(
    (image) => image.face_state && image.face_state !== 'scorable',
  ).length;
  const faceUnscored = Math.max(0, faceReviewImages.length - faceScored - faceNotScorable);
  // Style de caption : défaut AUTO (SDXL booru-native → booru tags ; sinon prose), surchargé par le sélecteur.
  const effCaptionMode = captionMode || (d.train_type === 'sdxl' ? 'booru' : 'prose');
  const recaptionableExisting = recaptionCounts.rewrite - recaptionCounts.blank;
  const confirmExternalVision = async (provider, count) => {
    if (provider === 'configured') return true;
    const warning = externalVisionWarning(provider, count);
    return confirm({ ...warning, tone: 'warning' });
  };
  const startClassification = async (provider) => {
    const needsDetails = Number(d?.coverage_plan?.summary?.unclassified || 0);
    if (await confirmExternalVision(provider, needsDetails)) ds.classify(provider);
  };
  const startCaptioning = async () => {
    if (await confirmExternalVision(captionProvider, keptUncaptioned)) {
      ds.caption(effCaptionMode, captionProvider);
    }
  };
  const startRecaption = async () => {
    const includeAsserted = replaceAsserted;
    try {
      if (!(await confirm({
        title: includeAsserted
          ? `Replace ${recaptionCounts.rewriteWithAsserted} caption entries?`
          : `Re-caption ${recaptionCounts.rewrite} kept images?`,
        message: recaptionConfirmation(
          d.kind || 'character', recaptionCounts, includeAsserted),
        confirmLabel: 'Continue',
        tone: 'warning',
      }))) return;
      if (includeAsserted && !(await confirm({
        title: 'Replace your captions too?',
        message: `This will overwrite ${recaptionCounts.asserted} caption${
          recaptionCounts.asserted === 1 ? '' : 's'} you wrote or corrected. This cannot be undone as one batch.`,
        confirmLabel: 'Replace my captions',
        tone: 'danger',
      }))) return;
      const remoteCount = includeAsserted
        ? recaptionCounts.rewriteWithAsserted : recaptionCounts.rewrite;
      if (!(await confirmExternalVision(captionProvider, remoteCount))) return;
      if (includeAsserted) await ds.recaption(effCaptionMode, true, captionProvider);
      else await ds.recaption(effCaptionMode, false, captionProvider);
    } finally {
      setReplaceAsserted(false);
    }
  };
  // Overlaid watermarks still awaiting removal → drives the "🧽 Clean (N)" button.
  const watermarkDetected = summary.watermark_detected
    ?? images.filter((i) => i.watermark_state === 'detected').length;
  // ── Grid tag-filter (session-only) ──────────────────────────────────────────
  // A tag is toggled in its list and mutually excluded from the other (a tag can't
  // be both hidden and isolated). Match mode follows the caption style so booru
  // captions match a whole tag, prose captions a whole word (see utils/tagFilter).
  const toggleTag = (setSelf, setOther) => (raw) => {
    const t = normalizeTag(raw);
    if (!t) return;
    setOther((prev) => prev.filter((x) => x !== t));
    setSelf((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]));
  };
  const toggleExclude = toggleTag(setExcludeTags, setIncludeTags);
  const toggleInclude = toggleTag(setIncludeTags, setExcludeTags);
  const clearFilters = () => { setExcludeTags([]); setIncludeTags([]); };
  const filtersActive = excludeTags.length > 0 || includeTags.length > 0;
  // The list actually rendered by the grid. Filtering here means select-all,
  // auto-triage and every bulk action operate ONLY on the visible images. The
  // Caption-tools counts keep using the full `images` list (global, never lies).
  const gridImages = filterImages(reviewGridImages, {
    excludes: excludeTags, includes: includeTags, mode: effCaptionMode,
  });
  const pending = summary.pending_generation ?? images.filter(
    (i) => i.status === 'pending' && !i.filename
      && !unresolvedRescueIds.has(i.id) && !unresolvedImprovementIds.has(i.id),
  ).length;
  const triage = summary.awaiting_triage ?? images.filter(
    (i) => i.status === 'pending' && i.filename
      && !unresolvedRescueIds.has(i.id) && !unresolvedImprovementIds.has(i.id),
  ).length;

  const toggleLeakReview = () => {
    onRevealOpenChange('leak-review', !showLeaks, setShowLeaks);
  };

  // Preflight and in-page repair links use the same canonical step routes as
  // the visible workflow navigation.
  const jumpTo = (step) => {
    onStepChange(workflowStepForTarget(step.targetId));
  };
  // Keep the inspected image in sync with poll refreshes (label/status updates).
  const viewImgLive = viewImg ? {
    ...(images.find((i) => i.id === viewImg.id) || viewImg),
    ...(viewImg._imageImprovementReviewPreview ? { filename: viewImg.filename } : {}),
    _rescueReviewPreview: !!viewImg._rescueReviewPreview,
    _imageImprovementReviewPreview: !!viewImg._imageImprovementReviewPreview,
  } : null;
  const viewImgImproving = viewImgLive ? images.some((image) => (
    image.derivation_kind === 'klein_image_improve'
      && image.parent_image_id === viewImgLive.id
      && image.status === 'pending'
  )) : false;
  const viewImgImprovementReady = viewImgLive ? images.some((image) => (
    image.derivation_kind === 'klein_image_improve'
      && image.parent_image_id === viewImgLive.id
      && image.status === 'pending'
      && !!image.filename
  )) : false;
  const canImproveViewImg = !!viewImgLive
    && !viewImgLive._rescueReviewPreview
    && !viewImgLive._imageImprovementReviewPreview
    && !isSmallImageRescueRow(viewImgLive)
    && viewImgLive.derivation_kind !== 'klein_image_improve'
    && !improvementPairIds.has(viewImgLive.id);
  // Export ZIP — shared by the header CTA and the Import & export row.
  // Guard-rails: untriaged images are silently EXCLUDED from the zip,
  // and uncaptioned kept ones export as trigger-only.
  const exportZipGuarded = async () => {
    if (triage && !(await confirm({
      title: 'Export without unreviewed images?',
      message: `${triage} images still await triage and will not be included in the ZIP.`,
      confirmLabel: 'Export anyway',
      tone: 'warning',
    }))) return;
    if (keptUncaptioned && !(await confirm({
      title: 'Export images without captions?',
      message: `${keptUncaptioned} kept images have no caption and will export with the trigger only.`,
      confirmLabel: 'Export anyway',
      tone: 'warning',
    }))) return;
    ds.exportZip();
    setSessionCompletedSteps((current) => ({ ...current, export: true }));
  };
  // The folder lives on the machine running the app, so a browser file-picker
  // can't select it — the user pastes the path instead.
  const importFolderPrompt = async () => {
    const p = await promptDialog({
      title: 'Import a dataset folder',
      message: 'Enter the path on the machine running the app. The folder should contain images and optional same-name .txt captions.',
      inputLabel: 'Dataset folder path',
      confirmLabel: 'Import folder',
    });
    if (p && p.trim()) ds.importDatasetFolder(p.trim());
  };

  // Amber "in progress" banner text. Captioning keeps its richer live count (derived
  // from the images themselves). Otherwise, when a server-side batch is running
  // (restored from ds.activity after a reload too), name it and show done/total —
  // e.g. "Scanning for watermarks… 12/64". CPU passes (face analysis, watermark
  // clean) don't pause ComfyUI, so their note omits that claim.
  const act = ds.activity;
  const scraperBusy = isScraperImportBlocked({ busy: ds.busy, activity: act });
  const remoteCaptioning = captionProvider !== 'configured'
    || /OpenAI|Gemini|ChatGPT/.test(String(act?.detail || ''));
  const activityBanner = ds.captioning
    ? `${act?.detail || `Captioning in progress — ${keptCaptioned}/${kept} captioned…`}${remoteCaptioning ? ' Images are being processed by the selected API.' : ' ComfyUI is paused.'}`
    : (() => {
        if (act) {
          const prog = activityProgress(act);
          // Passes that DON'T claim "ComfyUI is paused": the CPU ones, plus
          // 'generate' (engine-dependent — Nano Banana / ChatGPT don't touch
          // ComfyUI, and the Klein case is obvious from the tiles appearing).
          const cpu = act.kind === 'analyze_faces'
            || (act.kind === 'watermark_clean' && !String(act.detail || '').includes('GPU'))
            || act.kind === 'generate'
            || /OpenAI|Gemini|ChatGPT/.test(String(act.detail || ''));
          const label = {
            watermark_detect: `Scanning for watermarks…${prog}`,
            watermark_clean: `Cleaning watermarks…${prog}`,
            caption: `Captioning…${prog}`,
            recaption: `Re-captioning…${prog}`,
            analyze_faces: `Analyzing faces…${prog}`,
            classify: `Classifying framing…${prog}`,
            generate: `Generating variations…${prog}`,
          }[act.kind];
          if (label) {
            const detailed = act.detail || label;
            return `${detailed}${cpu ? '' : ' ComfyUI is paused during the pass.'}`;
          }
        }
        return 'GPU processing in progress (analysis / cropping / captioning)… ComfyUI is paused during the pass.';
      })();

  // The training surface remains mounted but hidden so its long-running poller
  // survives route changes. Only the active task is visible.
  const stepCls = (...slugs) => (slugs.includes(activeStep.slug) ? 'flex flex-col gap-3' : 'hidden');

  return (
    <div className="flex flex-col gap-3">
      {/* Dataset identity is context; the active workflow step owns the page h1
          and primary action. */}
      {/* relative z-30 : le header est un flex item ; sans stacking-context propre,
          le z-20 du menu « ⋯ More » resterait piégé sous les frères plus bas. */}
      <div className="relative z-30 flex items-center gap-2 flex-wrap">
        <button type="button" onClick={onBack}
          className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-border bg-surface text-content-muted hover:text-content hover:bg-surface-raised text-sm transition-colors">
          ← Datasets
        </button>
        <span className="text-content font-bold">{d.name}</span>
        {d.kind !== 'style' ? <button type="button"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(d.trigger_word || '');
              toast.success('Trigger word copied');
            } catch {
              toast.error('Could not copy the trigger word — select it and copy manually');
            }
          }}
          title="Copy the trigger word (to put in your prompts)"
          className="flex items-center gap-1 px-2 py-0.5 rounded-lg border border-indigo-400/40 bg-indigo-500/10 text-[0.6875rem]">
          <span className="text-content-subtle">trigger:</span>
          <code className="text-indigo-300 font-semibold">{d.trigger_word || '—'}</code>
          <span aria-hidden className="text-content-subtle">⧉</span>
        </button> : <span className="rounded-lg border border-border bg-surface px-2 py-0.5 text-content-subtle text-[0.6875rem]">
          Style LoRA · no prompt trigger
        </span>}
        <div className="ml-auto flex items-center gap-2">
          {/* summary en display:flex → pas de marqueur natif ; les items restent
              montés en permanence (details ne fait que masquer l'affichage). */}
          <details className="relative">
            <summary
              title="More dataset actions — edit settings, body fidelity"
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-border bg-surface text-content-muted hover:text-content hover:bg-surface-raised text-sm cursor-pointer select-none">
              ⋯ More
            </summary>
            <div className="absolute right-0 top-full mt-1 z-20 w-72 rounded-lg border border-border bg-surface-overlay shadow-xl p-1.5 flex flex-col gap-0.5">
              <button type="button" onClick={() => setSettingsOpen(true)}
                title="Edit the dataset name, trigger word, and (for concept datasets) the concept description that drives the caption avoid-list."
                className={MENU_ITEM}>
                ⚙️ Edit settings
                <span className="ml-auto text-content-subtle text-[0.625rem]">
                  name · trigger{concept ? ' · concept' : ''}
                </span>
              </button>
              {!concept && (
                <button type="button" disabled={ds.busy}
                  onClick={() => ds.setDatasetFidelity?.(bodyFid ? 'face' : 'body')}
                  title={bodyFid
                    ? 'Body fidelity ON: captions also omit tattoos/scars/marks (they bind to the trigger), composition targets more bust/body shots, imports keep the full frame by default. Click to go back to face-only.'
                    : 'Face-only fidelity (default): the LoRA learns the face; body shape follows the prompt. Click for FULL-BODY fidelity (body shape & marks bind to the trigger too).'}
                  className={`${MENU_ITEM} ${bodyFid ? 'text-emerald-300' : ''}`}>
                  🧍 Body fidelity
                  <span className={`ml-auto text-[0.625rem] ${bodyFid ? 'text-emerald-300 font-semibold' : 'text-content-subtle'}`}>
                    {bodyFid ? '✓ on' : 'off'}
                  </span>
                </button>
              )}
            </div>
          </details>
        </div>
      </div>

      <div className="lg:grid lg:grid-cols-[16rem_minmax(0,1fr)] lg:gap-5 lg:items-start">
        <aside>
          <div className="lg:sticky lg:top-20">
            <DatasetWorkflowNav steps={workflowSteps} currentSlug={activeStep.slug}
              onNavigate={onStepChange} />
          </div>
        </aside>

        <div className="flex flex-col gap-3 min-w-0 mt-1 lg:mt-0">
          <header className="border-b border-border pb-3">
            <div className="flex flex-wrap items-center gap-2">
              <p className="m-0 font-mono text-[11px] uppercase tracking-[0.18em] text-content-subtle">
                Step {workflowSteps.findIndex((step) => step.slug === activeStep.slug) + 1} of {workflowSteps.length}
              </p>
              {activeStep.optional && (
                <span className="rounded-full border border-border px-2 py-0.5 text-[0.625rem] font-semibold text-content-subtle">
                  Optional
                </span>
              )}
            </div>
            <h1 id="dataset-step-heading" tabIndex={-1}
              className="m-0 mt-1 text-xl font-semibold text-content focus:outline-none">
              {activeStep.label}
            </h1>
            <p className="m-0 mt-1 max-w-3xl text-sm leading-relaxed text-content-muted">
              {activeStep.description}
            </p>
          </header>

          {workflowSteps.find((step) => step.slug === activeStep.slug)?.unavailable && (
            <div role="note" className="rounded-lg border border-amber-400/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-100">
              {workflowSteps.find((step) => step.slug === activeStep.slug).unavailableReason}.{' '}
              You can configure it in <button type="button" onClick={() => navigate('/setup')}
                className="font-semibold underline">Setup</button>, or skip this optional step.
            </div>
          )}

          {ds.busy && (
            <div className="flex items-center gap-2 rounded-lg border border-amber-400/40 bg-amber-400/10 px-3 py-2">
              <span className="inline-block w-4 h-4 border-2 border-amber-400/40 border-t-amber-400 rounded-full animate-spin" aria-hidden />
              <span className="text-content text-sm">{activityBanner}</span>
            </div>
          )}

          {imageHydrationError && (section === 'curation' || section === 'captions') && (
            <div role="alert"
              className="flex items-center gap-3 rounded-lg border border-red-400/40 bg-red-500/10 px-3 py-2">
              <span className="text-content text-sm">
                Couldn’t load every image for this review. Review actions stay paused until all images are loaded.
              </span>
              <button type="button" onClick={loadAllImages} disabled={loadingMoreImages}
                className="ml-auto shrink-0 rounded-lg border border-red-300/40 px-3 py-1.5 text-sm font-semibold text-red-100 disabled:opacity-40">
                Retry
              </button>
            </div>
          )}

          {pending > 0 && (
            <div className="flex items-center gap-3 rounded-lg border-2 border-indigo-400/60 bg-indigo-500/15 px-3 py-2.5">
              <span className="animate-pulse text-lg" aria-hidden>⏳</span>
              <div className="flex flex-col">
                <span className="text-content text-sm font-semibold">
                  {pending} generation(s) in progress…
                </span>
                <span className="text-content-subtle text-[0.6875rem]">
                  First results look wrong? Stop now — the remaining API calls are skipped (not billed).
                </span>
              </div>
              <button type="button" onClick={ds.cancelPending} disabled={ds.busy}
                title="Cancels every generation still in flight; finished images stay."
                className="ml-auto shrink-0 px-4 py-2 rounded-lg bg-red-600 hover:bg-red-500 text-white text-sm font-bold disabled:opacity-40">
                ⏹ Stop generation
              </button>
            </div>
          )}

          {activeStep.slug === 'score' && (
            <div className="flex flex-col gap-2 rounded-lg border border-border bg-surface px-3 py-3">
              <button id="ds-curation-face-analysis" type="button" data-workspace-focus
                onClick={ds.analyzeFaces} disabled={ds.busy || !d.ref_filename || !caps.face_scoring}
                title={!caps.face_scoring ? 'Configure face scoring in Setup'
                  : d.ref_filename ? "Scores each image's facial resemblance vs the reference (deletes nothing)" : "Set a reference photo first"}
                className="self-start rounded-lg border border-border px-3 py-1.5 text-sm font-semibold text-content disabled:opacity-40">
                {ds.analyzing
                  ? `🎭 Analyzing…${activityProgress(act, 'analyze_faces')}`
                  : '🎭 Analyze faces'}
              </button>
              {!d.ref_filename && (
                <p className="m-0 text-sm text-content-muted">
                  Set a primary reference before scoring, or skip this optional step.
                </p>
              )}
              {d.ref_filename && (
                <div role="status" className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-content-muted">
                  <span><strong className="text-content">{faceScored}</strong> scored</span>
                  <span><strong className="text-content">{faceNotScorable}</strong> not scorable</span>
                  <span className={faceUnscored ? 'text-amber-200' : ''}>
                    <strong>{faceUnscored}</strong> not analyzed
                  </span>
                  {faceUnscored > 0 && !ds.analyzing && (
                    <span className="basis-full text-amber-200">
                      No stored result exists for these photos. Run Analyze faces; if it finishes without scores,
                      use Setup → Quality tools to check the scorer.
                    </span>
                  )}
                </div>
              )}
            </div>
          )}

          {/* The curation grid is also useful evidence on the optional scoring
              page, but no unrelated setup or export controls are shown there. */}
          <div className={stepCls('curate', 'score')}>
            <p className="m-0 text-content-subtle text-[0.75rem] tabular-nums">
              {totalImages} image(s) · {kept} kept
              {images.length < totalImages ? ` · ${images.length} loaded` : ''}
              {triage > 0 ? <> · <span className="text-amber-300">{triage} awaiting ✓/✕</span></> : ''}
              {rescueReviewCount > 0
                ? <> · <span className="text-indigo-300">{rescueReviewCount} Klein rescue pair(s) in Curation</span></>
                : ''}
              {unresolvedImprovementPairs.length > 0
                ? <> · <span className="text-cyan-300">{unresolvedImprovementPairs.length} reconstruction(s) in Curation</span></>
                : ''}
              {kept > 0 ? ` · ${keptCaptioned}/${kept} captioned` : ''}
              {watermarkDetected > 0 ? ` · ${watermarkDetected} watermark(s) flagged` : ''}
            </p>
            <div id="gf-images" className="scroll-mt-20 flex flex-col gap-2">
              {filtersActive && (
                <GridFilterBar excludes={excludeTags} includes={includeTags}
                  shown={gridImages.length} total={reviewGridImages.length}
                  onRemoveExclude={toggleExclude} onRemoveInclude={toggleInclude}
                  onClearAll={clearFilters} />
              )}
              {filtersActive && gridImages.length === 0 ? (
                // Filtered down to nothing: say so plainly (the grid's own "no images"
                // empty-state would read as "everything's gone", which would be a lie).
                <p className="rounded-lg border border-border bg-surface px-3 py-4 text-center text-content-subtle text-sm">
                  No images match the active filter{excludeTags.length + includeTags.length > 1 ? 's' : ''} —{' '}
                  <button type="button" onClick={clearFilters} className="underline hover:text-content">clear all</button>{' '}
                  to see all {images.length} again.
                </p>
              ) : (
                <DatasetGrid
                  images={activeStep.slug === 'score'
                    ? images.filter((image) => image.status === 'keep' && image.filename)
                    : gridImages}
                  datasetId={d.id} onStatus={ds.setStatus} onCaption={ds.setCaption}
                  onCrop={setCropImg} onDelete={ds.deleteImage}
                  onRegenerate={ds.regenerate} onView={setViewImg}
                  onBatch={ds.batchImages} busy={ds.busy}
                  nonces={ds.nonces} faceThresholds={d.face_thresholds}
                  exclusiveImageIds={unresolvedExclusiveIds}
                  hasMore={ds.hasMoreImages} onLoadMore={ds.loadMoreImages}
                  loadingMore={ds.loadingMoreImages} totalImages={totalImages}
                  reviewOnly={activeStep.slug === 'score'}
                  showCaptions={activeStep.slug !== 'score'} />
              )}
            </div>
          </div>

          <div className={stepCls('import', 'review', 'anchors', 'coverage', 'reference', 'generate')}>
            {activeStep.slug === 'import' && (
              <div className="flex flex-col gap-3">
                <div id="ds-add-scraper" tabIndex={-1} className="scroll-mt-20">
                  {concept ? (
                    <ConceptSourcesPanel key={`scraper-${d.id}`} datasetId={d.id}
                      onImport={ds.scrapeImport} busy={scraperBusy} />
                  ) : (
                    <details open={scraperOpen}
                      className="rounded-lg border border-border bg-surface open:pb-3">
                      <summary onClick={(event) => {
                        event.preventDefault();
                        onRevealOpenChange('scraper', !scraperOpen, setScraperOpen);
                      }} className="cursor-pointer select-none px-3 py-2 text-sm font-semibold text-content">
                        🕸 Import from a gallery URL
                        <span className="ml-2 font-normal text-content-subtle text-[0.6875rem]">
                          optional alternative to uploading files
                        </span>
                      </summary>
                      <div className="px-3">
                        <ConceptSourcesPanel key={`scraper-${d.id}`} datasetId={d.id}
                          onImport={ds.scrapeImport} busy={scraperBusy} />
                      </div>
                    </details>
                  )}
                </div>
                <div id="ds-add-import" tabIndex={-1} className="scroll-mt-20">
                  <ImportDropzone key={`${d.id}-${bodyFid}`}
                    onImport={(files, options) => ds.importFiles(files, options)} busy={ds.busy}
                    cropOption={!concept} defaultCrop={false} />
                </div>
                <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2">
                  <button type="button" onClick={() => zipInput.current?.click()} disabled={ds.busy}
                    className="rounded-lg border border-border px-3 py-1.5 text-sm text-content disabled:opacity-40">
                    📦 Import an existing dataset ZIP
                  </button>
                  <button type="button" disabled={ds.busy} onClick={importFolderPrompt}
                    className="rounded-lg border border-border px-3 py-1.5 text-sm text-content disabled:opacity-40">
                    📂 Import an existing dataset folder
                  </button>
                  <span className="text-[0.6875rem] text-content-subtle">
                    merges images and same-name caption files; duplicates are skipped
                  </span>
                </div>
                <input ref={zipInput} type="file" accept=".zip,application/zip" className="hidden"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file) ds.importDatasetZip(file);
                    event.target.value = '';
                  }} />
              </div>
            )}

            {activeStep.slug === 'review' && (
              <CorpusWorkbench mode="review" datasetId={d.id} images={images}
                coveragePlan={d.coverage_plan}
                onAnalyze={ds.analyzeCorpus} onSourceRights={ds.setSourceRights}
                onStatus={ds.setStatus} onBatch={ds.batchImages}
                reviewPairIds={unresolvedExclusiveIds} faceThresholds={d.face_thresholds}
                busy={ds.busy} />
            )}

            {activeStep.slug === 'anchors' && (
              <CorpusWorkbench mode="anchors" datasetId={d.id} images={images}
                anchorPlan={d.anchor_plan} coveragePlan={d.coverage_plan}
                onAnalyze={ds.analyzeCorpus} onAnchorDecision={ds.setAnchorDecision}
                onSourceRights={ds.setSourceRights} onStatus={ds.setStatus}
                reviewPairIds={unresolvedExclusiveIds} faceThresholds={d.face_thresholds}
                busy={ds.busy} />
            )}

            {activeStep.slug === 'coverage' && (
              <>
                <CorpusWorkbench mode="coverage" datasetId={d.id} images={images}
                  anchorPlan={d.anchor_plan} coveragePlan={d.coverage_plan}
                  onAnalyze={ds.analyzeCorpus} onClassify={startClassification}
                  onAnchorDecision={ds.setAnchorDecision} onCoverage={ds.setCoverage}
                  onSourceRights={ds.setSourceRights}
                  onStatus={ds.setStatus} onBatch={ds.batchImages}
                  reviewPairIds={unresolvedExclusiveIds} faceThresholds={d.face_thresholds}
                  busy={ds.busy}
                  visionAvailable={Boolean(localVisionStep?.runtimeReady)}
                  classificationProvider={classificationProvider}
                  onClassificationProviderChange={setClassificationProvider}
                  visionUnavailableReason={localVisionGateReason(localVisionStep)} />
                <CoveragePlan plan={d.coverage_plan} onPolicyChange={ds.setCoveragePolicy}
                  onGoToGenerate={() => jumpTo({ targetId: 'ds-add-generate' })} />
              </>
            )}

            {activeStep.slug === 'reference' && (
              <div id="gf-reference" className="scroll-mt-20 flex flex-col gap-2">
                <p className="m-0 text-sm text-content-muted">
                  Local Klein generation and face scoring use this image. Remote image providers can
                  use the reviewed generation photos instead, so you may skip this page.
                </p>
                <div id="ds-add-reference" tabIndex={-1}>
                  <ReferencePanel refFilename={d.ref_filename} datasetId={d.id} onSetRef={ds.setRef}
                    onCropRef={() => setRefCrop(true)} busy={ds.busy} nonce={ds.refNonce}
                    extraRefs={d.ref_extra_filenames || []}
                    onAddExtraRef={ds.addExtraRef} onRemoveExtraRef={ds.removeExtraRef} />
                </div>
              </div>
            )}

            {activeStep.slug === 'generate' && (
              <div id="gf-generate" className="scroll-mt-20 flex flex-col gap-2">
                <CompositionBar composition={d.composition} upscaled={d.composition_upscaled}
                  bodyFidelity={bodyFid} targets={d.coverage_plan?.targets} />
                <div id="ds-add-generate" tabIndex={-1}>
                  <VariationCatalog key={`vc-${d.id}-${bodyFid}`} busy={ds.busy}
                      generating={act && act.kind === 'generate' ? act : null}
                      onGenerate={async (...args) => {
                        // Guard-rail: a batch is already in flight — launching another one
                        // on top is usually an accidental double-click, not a plan.
                        if (pending > 0 && !(await confirm({
                          title: 'Launch another generation batch?',
                          message: `A generation batch is already running with ${pending} images in flight. Launching another may compete for the same engine.`,
                          confirmLabel: 'Launch another',
                          tone: 'warning',
                        }))) return;
                        ds.generate(...args);
                      }}
                      hasRef={!!d.ref_filename || images.some((img) => img.source === 'import'
                        && img.filename && img.status === 'keep')}
                      hasPrimaryRef={!!d.ref_filename} composition={d.composition} images={images}
                      variationLabelCounts={d.image_summary?.variation_label_counts}
                      bodyFidelity={bodyFid}
                      recommendedIds={d.coverage_plan?.recommended_variation_ids}
                      coverageTargets={d.coverage_plan?.targets}
                      anchorPlan={d.anchor_plan} />
                </div>
              </div>
            )}
          </div>

          {/* ============ 🧹 Curation — passes de qualité sur les images gardées :
               ressemblance faciale, watermarks (find → clean → review), purge. */}
          <div className={stepCls('curate', 'score')}>
            {reviewNeedsHydration ? (
              <div role="status" className="rounded-lg border border-border bg-surface px-3 py-4 text-content-subtle text-sm">
                {imageHydrationError ? 'Retry loading to unlock full-dataset curation.' : 'Loading every image before full-dataset curation…'}
              </div>
            ) : (
              <div id="gf-curation" className="scroll-mt-20 flex flex-col gap-2">
              {activeStep.slug === 'curate' && (
                <>
                  <CurationHistory datasetId={d.id} refreshKey={curationHistoryKey}
                    onUndo={ds.undoCuration} />
                  <SmallImageRescueReview images={images} datasetId={d.id}
                    onResolve={ds.resolveSmallImageRescue}
                    onPreview={(image) => setViewImg({ ...image, _rescueReviewPreview: true })}
                    nonces={ds.nonces} />
                  <ImageImprovementReview images={images} datasetId={d.id}
                    onResolve={ds.resolveImageImprovement} onPreview={setViewImg} />
                </>
              )}
              <div className="flex items-center gap-2 flex-wrap rounded-lg border border-border bg-surface px-3 py-2">
                <div id="ds-curation-watermarks" tabIndex={-1}
                  className="flex items-center gap-2 flex-wrap scroll-mt-20">
                {/* Watermark auto-correction (V1): find overlaid site logos/URLs/usernames on
                    the kept images, then Clean them (border → crop, small off-center → LaMa
                    inpaint, on-subject → manual review). Applies to any dataset kind. */}
                <button type="button" data-workspace-focus onClick={ds.findWatermarks} disabled={ds.busy}
                  title="Scans the kept images for overlaid watermarks/logos/URLs added on top of the photo (deletes nothing)"
                  className="px-3 py-1.5 rounded-lg bg-surface text-content text-sm disabled:opacity-40 border border-border">
                  {ds.watermarking
                    ? `🧽 Scanning…${activityProgress(act, 'watermark_detect')}`
                    : '🧽 Find watermarks'}
                </button>
                {watermarkDetected > 0 && (
                  <button type="button" onClick={ds.cleanWatermarks} disabled={ds.busy}
                    title={caps.watermark_inpaint
                      ? 'Removes them: border marks are cropped, small off-center marks are inpainted (LaMa), on-subject marks are flagged for manual review'
                      : 'Removes border marks by cropping. Inpainting (LaMa) needs a one-time install — use ⬇ Install inpainting next to this button; off-center marks are skipped until then'}
                    className="px-3 py-1.5 rounded-lg bg-amber-500/15 border border-amber-400/40 text-amber-200 text-sm font-semibold disabled:opacity-40">
                    🧽 Clean ({watermarkDetected})
                  </button>
                )}
                {/* Per-image control: step through the flagged images full-screen, see each
                    detected box, and Clean / dismiss (false positive) / reject one by one.
                    The auto-detect has false positives, so this hands the final call to the
                    user (crucial after the "64/75 flagged" real-dataset run). */}
                {watermarkDetected > 0 && (
                  <button id="ds-curation-review-flagged" type="button" data-workspace-focus
                    disabled={ds.busy}
                    onClick={() => setReviewQueue(images.filter((i) => i.watermark_state === 'detected'))}
                    title="Step through the flagged images one by one — see each detected box and Clean, dismiss a false positive, or reject"
                    className="px-3 py-1.5 rounded-lg bg-surface border border-border text-content text-sm disabled:opacity-40 scroll-mt-20">
                    🔍 Review flagged ({watermarkDetected})
                  </button>
                )}
                {/* Watermark inpainting (LaMa) needs its Torch/Pillow/OpenCV runtime.
                    Show a scoped installer RIGHT HERE — where the lack is
                    met — instead of sending the user back to Setup's whole ML-extras
                    step. Toggles a panel below (InstallRunner does the polling +
                    progress + manual-command fallback); on success caps re-fetch and
                    this affordance disappears. */}
                {!caps.watermark_inpaint && (
                  <button type="button" onClick={() => setInstallInpaintOpen((v) => !v)}
                    aria-expanded={installInpaintOpen}
                    title="Install the watermark-inpainting runtime (LaMa) so off-center marks can be repainted instead of only cropped. One-time download (~hundreds of MB)."
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-dashed border-amber-400/50 bg-amber-500/5 text-amber-200/90 text-sm hover:bg-amber-500/10">
                    ⬇ Install inpainting
                    <span className="text-content-subtle text-[0.625rem] font-normal">one-time · ~hundreds of MB</span>
                    <span aria-hidden className="text-content-subtle text-xs">{installInpaintOpen ? '▴' : '▾'}</span>
                  </button>
                )}
                </div>
              </div>

              {/* Scoped watermark-inpainting installer. Reuses the Setup InstallRunner
                  (same polling / live progress / manual-command fallback). onDone
                  force-refreshes capabilities → watermark_inpaint flips true without a
                  restart or the 600 s probe TTL (the backend drops the import cache on
                  success), and the affordance above unmounts on its own. */}
              {activeStep.slug === 'curate' && installInpaintOpen && !caps.watermark_inpaint && (
                <div className="rounded-lg border border-amber-400/40 bg-amber-500/5 p-3 flex flex-col gap-2">
                  <div className="flex items-start gap-2">
                    <span aria-hidden className="text-lg leading-none">🧽</span>
                    <div className="flex flex-col">
                      <span className="text-amber-200 text-sm font-semibold">Install watermark inpainting (LaMa)</span>
                      <span className="text-content-subtle text-[0.6875rem]">
                        Adds the verified LaMa runtime
                        (pulls Torch — one-time download, ~hundreds of MB). No restart, no GPU required:
                        once done, ⬇ inpaints small off-center marks instead of skipping them.
                      </span>
                    </div>
                    <button type="button" onClick={() => setInstallInpaintOpen(false)}
                      className="ml-auto shrink-0 text-content-subtle hover:text-content text-sm"
                      aria-label="Close the inpainting installer">✕</button>
                  </div>
                  <InstallRunner action="watermark_inpaint" buttonLabel="⬇ Download & install"
                    onDone={() => refreshCaps(true)} />
                </div>
              )}

              {/* Recoverable cleanup of rejected/failed rows lives alongside the
                  other curation actions. */}
              {activeStep.slug === 'curate' && unused > 0 && (
                <div id="ds-curation-rejected-cleanup" tabIndex={-1}
                  className="flex items-center gap-2 flex-wrap rounded-lg border border-border bg-surface px-3 py-2 scroll-mt-20">
                  <button type="button" data-workspace-focus disabled={ds.busy}
                    onClick={async () => {
                      if (await confirm({
                        title: `Move ${unused} rejected or failed image${unused === 1 ? '' : 's'} to Trash?`,
                        message: 'The images remain recoverable in Settings until you empty the Trash.',
                        confirmLabel: 'Move to Trash',
                        tone: 'danger',
                      })) ds.purgeUnused();
                    }}
                    title="Move rejected and failed images to Trash"
                    className="px-3 py-1.5 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-sm disabled:opacity-40">
                    🧹 Trash rejected/failed ({unused})
                  </button>
                  <span className="text-content-subtle text-[0.6875rem]">
                    rejected images never train; empty Trash later to reclaim disk space
                  </span>
                </div>
              )}
              </div>
            )}
          </div>

          {/* ============ ✍️ Captions — générer/regénérer les captions, surveiller
               les fuites (identité/concept), outils de masse (find/replace, tags). */}
          <div className={stepCls('captions')}>
            {reviewNeedsHydration ? (
              <div role="status" className="rounded-lg border border-border bg-surface px-3 py-4 text-content-subtle text-sm">
                {imageHydrationError ? 'Retry loading to unlock full-dataset caption review.' : 'Loading every image before full-dataset caption review…'}
              </div>
            ) : (
              <div id="gf-captions" className="scroll-mt-20 flex flex-col gap-2">
              <div id="ds-captions-generate" tabIndex={-1}
                className="flex items-center gap-2 flex-wrap rounded-lg border border-border bg-surface px-3 py-2 scroll-mt-20">
                {!concept && (
                  <select value={effCaptionMode} onChange={(e) => setCaptionMode(e.target.value)} disabled={ds.busy}
                    title="Caption style — Prose (Z-Image) or Booru tags (SDXL booru-native, e.g. bigLove). Defaults to auto based on the dataset's type."
                    className="px-2 py-1.5 rounded-lg bg-surface border border-border text-content text-[0.8125rem] disabled:opacity-40">
                    <option value="prose">📝 Prose</option>
                    <option value="booru">🏷️ Booru tags</option>
                  </select>
                )}
                <select value={captionProvider} onChange={(event) => setCaptionProvider(event.target.value)}
                  disabled={ds.busy} aria-label="Captioning provider"
                  className="px-2 py-1.5 rounded-lg bg-surface border border-border text-content text-[0.8125rem] disabled:opacity-40">
                  {EXTERNAL_VISION_PROVIDERS.map((provider) => (
                    <option key={provider.id} value={provider.id}>{provider.label}</option>
                  ))}
                </select>
                <button type="button" data-workspace-focus
                  onClick={startCaptioning} disabled={ds.busy}
                  className="px-3 py-1.5 rounded-lg bg-gradient-primary text-white text-sm font-semibold disabled:opacity-40">
                  {ds.captioning ? `✨ ${keptCaptioned}/${kept} captioned…` : '✨ Caption the kept ones'}
                </button>
                <button type="button"
                  disabled={ds.busy || (!recaptionableExisting && !replaceAsserted)}
                  onClick={startRecaption}
                  title={!recaptionableExisting && recaptionCounts.asserted
                    ? 'Every existing caption is yours. Select the explicit override to replace them.'
                    : isConcept
                    ? "Re-generates every caption while keeping the recurring concept unspoken"
                    : isStyle
                      ? "Re-generates every caption as content-only text without naming the aesthetic"
                      : "Re-generates every caption without describing identity (face/hair)"}
                  className="px-3 py-1.5 rounded-lg bg-surface text-content text-sm disabled:opacity-40 border border-border">
                  🔄 Re-caption
                </button>
                {recaptionCounts.asserted > 0 && (
                  <label className="flex items-center gap-1.5 rounded-lg border border-indigo-400/30 bg-indigo-500/10 px-2 py-1.5 text-xs text-indigo-100">
                    <input type="checkbox" checked={replaceAsserted}
                      onChange={(event) => setReplaceAsserted(event.target.checked)}
                      disabled={ds.busy}
                      className="h-3.5 w-3.5 accent-indigo-500" />
                    Also replace captions I wrote ({recaptionCounts.asserted})
                  </label>
                )}
                {captionProvider !== 'configured' && (
                  <p className="basis-full m-0 text-[0.6875rem] text-amber-200">
                    Each captioned photo will leave this machine and be sent to the selected provider after confirmation.
                  </p>
                )}
                {/* Caption-leak badge — KIND-aware. character: identity words
                    (hair/face/skin); concept: the caption NAMING the concept (must bind to
                    the trigger, not the words); style: not applicable (the subjects'
                    description IS the content). BOTH count states are clickable → the same
                    explainer panel; the count is spelled out ("N checked") so a green 0
                    reads as a REAL result, not a scan that never ran. */}
                {isStyle ? (
                  <span className="ml-auto text-content-subtle text-[0.8125rem]"
                    title="Style captions describe controllable content but should not name the aesthetic, medium or artist. The caption prompt enforces this rule; there is no automatic style-term scanner yet.">
                    style captions: content only · aesthetic terms stay unspoken
                  </span>
                ) : d.caption_leak && (
                  d.caption_leak.captioned > 0 ? (
                    <button id="ds-captions-leak-review" type="button" data-workspace-focus
                      onClick={toggleLeakReview}
                      aria-expanded={showLeaks}
                      title={d.caption_leak.leaking === 0
                        ? (isConcept
                            ? "0 captions name the concept — it binds to the trigger. Click for what was checked and why."
                            : "0 captions describe hair/face/skin — identity binds to the trigger. Click for what was checked and why.")
                        : (isConcept
                            ? "These captions name the concept → it won't bind to the trigger. Click to see what's watched and fix them here."
                            : "These captions mention hair/face/skin → identity won't bind to the trigger. Click to see what's watched and fix them here.")}
                      className={`ml-auto text-[0.8125rem] underline decoration-dashed scroll-mt-20 ${
                        d.caption_leak.leaking === 0
                          ? 'text-emerald-400 decoration-emerald-400/40'
                          : 'text-amber-400 decoration-amber-400/50'}`}>
                      {d.caption_leak.leaking === 0
                        ? `✅ 0 ${isConcept ? 'concept' : 'identity'} leaks · ${d.caption_leak.captioned} captions checked`
                        : `⚠️ ${d.caption_leak.leaking}/${d.caption_leak.captioned} captions leak ${isConcept ? 'the concept' : 'identity'}`}
                      {' '}{showLeaks ? '▴' : '▾'}
                    </button>
                  ) : kept > 0 ? (
                    <button id="ds-captions-leak-review" type="button" data-workspace-focus
                      onClick={toggleLeakReview}
                      aria-expanded={showLeaks}
                      title={`The ${isConcept ? 'concept' : 'identity'}-leak scan runs on captions. Caption the kept images first. Click to learn what it checks.`}
                      className="ml-auto text-content-subtle text-[0.8125rem] underline decoration-dashed decoration-border scroll-mt-20">
                      {isConcept ? 'concept' : 'identity'}-leak scan: no captions yet {showLeaks ? '▴' : '▾'}
                    </button>
                  ) : null
                )}
              </div>

              {/* Caption-leak explainer + triage. Opened from the badge in EITHER state:
                  it says what a leak is (kind-specific: identity vs the concept itself),
                  WHAT was checked (so a green 0 is a real result, not a check that never
                  ran), why 0 is normal — and, when there ARE leaks, the offending captions
                  editable IN PLACE (saves on blur, like the grid). Style sets have no leak
                  concept, so the panel only opens for character/concept. */}
              {showLeaks && !isStyle && (
                <div className="rounded-lg border border-border bg-surface-raised p-3 flex flex-col gap-3 text-[0.75rem]">
                  <div className="flex items-start gap-2">
                    <span aria-hidden className="text-base leading-none">🎭</span>
                    <div className="flex flex-col gap-1">
                      <span className="text-content font-semibold text-sm">{isConcept ? 'Concept-leak check' : 'Identity-leak check'}</span>
                      {isConcept ? (
                        <p className="m-0 text-content-muted leading-relaxed">
                          A <strong className="text-content">concept leak</strong> is a word in a caption
                          that names <em>the concept itself</em> — the recurring element every image in
                          the set shares. On a concept LoRA these words must stay OUT of the captions:
                          they bind the concept to the text instead of to your trigger word{' '}
                          <code className="text-indigo-300">{d.trigger_word || 'your trigger'}</code>.
                          Describe the person and scene freely, but leave the concept
                          {d.concept_desc ? <> (<em className="text-content-muted">{d.concept_desc}</em>)</> : null}
                          {' '}unspoken so it binds to the trigger, not the caption.
                        </p>
                      ) : (
                        <p className="m-0 text-content-muted leading-relaxed">
                          An <strong className="text-content">identity leak</strong> is a word in a caption
                          that describes <em>who the person is</em> — hair, eye or skin colour, facial
                          features. On a character LoRA these words must stay OUT of the captions: they
                          dilute the identity into the text instead of binding it to your trigger word{' '}
                          <code className="text-indigo-300">{d.trigger_word || 'your trigger'}</code>.
                        </p>
                      )}
                    </div>
                    <button type="button" onClick={toggleLeakReview}
                      className="ml-auto shrink-0 text-content-subtle hover:text-content text-sm" aria-label="Close">✕</button>
                  </div>

                  {/* What was checked — the numbers behind the badge. */}
                  <div className="flex flex-wrap gap-x-4 gap-y-1 text-content-subtle tabular-nums">
                    <span><strong className="text-content-muted">{d.caption_leak?.captioned ?? 0}</strong> captions checked</span>
                    <span className={d.caption_leak?.leaking ? 'text-amber-300' : 'text-emerald-400'}>
                      <strong>{d.caption_leak?.leaking ?? 0}</strong> leaking
                    </span>
                    <span className="text-content-subtle/70">re-scanned live on every caption change</span>
                  </div>

                  {/* Words the detector watches. Concept: derived from the description
                      (its words + their basic lexical field); character: the fixed regex. */}
                  <div className="flex flex-col gap-1">
                    <span className="text-content-subtle">Words watched for:</span>
                    {isConcept ? (
                      <p className="m-0 text-content-muted leading-relaxed">
                        The words of the concept description
                        {d.concept_desc ? <> (<em className="text-content-muted">{d.concept_desc}</em>)</> : null}
                        {' '}and their basic lexical field — the body parts and positions it refers to
                        (e.g. a leg pose also watches <em>knees, feet, thighs, lifted, raised</em>), so a
                        periphrase can’t sneak the concept back into the caption.
                      </p>
                    ) : (
                      <div className="flex flex-wrap gap-1.5">
                        {['hair', 'eye colour', 'skin · complexion · freckles',
                          'jawline · eyebrows · facial features', 'face shape',
                          ...(bodyFid ? ['tattoos · scars · piercings (body fidelity)'] : [])].map((c) => (
                          <span key={c} className="rounded-full bg-surface border border-border px-2 py-0.5 text-content-muted text-[0.6875rem]">{c}</span>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Why a green 0 is expected, not suspicious. */}
                  {d.caption_leak?.captioned === 0 ? (
                    <p className="m-0 text-content-subtle leading-relaxed">
                      Nothing checked yet — the scan runs on captions. Caption the kept images first.
                    </p>
                  ) : d.caption_leak?.leaking === 0 ? (
                    <p className="m-0 text-emerald-400/90 leading-relaxed">
                      {isConcept
                        ? <>✅ All clear — every caption describes the scene while leaving the concept
                          unspoken, so it will bind to your trigger. It’s a real result on {d.caption_leak?.captioned} caption(s),
                          not a check that didn’t run.</>
                        : <>✅ All clear — and this is expected. The app’s captioner is built to describe pose,
                          clothing, setting and framing but never the person’s identity, so a clean character
                          set genuinely reads 0. It’s a real result on {d.caption_leak?.captioned} caption(s),
                          not a check that didn’t run.</>}
                    </p>
                  ) : (
                    <div className="rounded-lg border border-amber-400/40 bg-amber-500/5 p-2.5 flex flex-col gap-2">
                      <span className="text-amber-300 text-[0.8125rem] font-semibold">
                        {isConcept
                          ? <>Captions naming the concept ({d.caption_leak?.leaking}) — remove the concept words, or 🔄 Re-caption. Edits save when you click away.</>
                          : <>Captions leaking identity ({d.caption_leak?.leaking}) — remove the highlighted words, or 🔄 Re-caption. Edits save when you click away.</>}
                      </span>
                      {images.filter((i) => i.leak).map((img) => (
                        <div key={img.id} className="flex gap-2 items-start">
                          <img src={datasetImageUrl(d.id, img)}
                            alt={img.variation_label || 'dataset image'} loading="lazy"
                            className="w-14 h-14 rounded-lg object-cover shrink-0 bg-black" />
                          <textarea defaultValue={img.caption || ''} rows={2}
                            onBlur={(e) => {
                              if (e.target.value !== (img.caption || '')) ds.setCaption(img.id, e.target.value);
                            }}
                            aria-label={`Caption of image ${img.id}`}
                            className="flex-1 bg-app/60 border border-amber-400/30 rounded px-2 py-1 text-[0.6875rem] text-content resize-y" />
                        </div>
                      ))}
                      {images.filter((i) => i.leak).length === 0 && (
                        <p className="m-0 text-emerald-400 text-[0.8125rem]">✅ All clear — no leaking caption left.</p>
                      )}
                    </div>
                  )}
                </div>
              )}

              <div id="ds-captions-tools" tabIndex={-1} className="scroll-mt-20">
                <CaptionToolsBar images={images} kind={d.kind || 'character'} mode={effCaptionMode}
                  excludes={excludeTags} includes={includeTags}
                  onExclude={toggleExclude} onInclude={toggleInclude}
                  onReplace={ds.replaceCaptions}
                  onWriteFiles={ds.writeCaptionFiles} onOpenFolder={ds.openDatasetFolder}
                  busy={ds.busy}
                  open={captionToolsOpen}
                  onOpenChange={(open) => onRevealOpenChange('tools', open, setCaptionToolsOpen)} />
              </div>
              <section aria-labelledby="caption-review-heading" className="flex flex-col gap-2 pt-1">
                <div>
                  <h3 id="caption-review-heading" className="m-0 text-sm font-semibold text-content">
                    Review every kept image and caption
                  </h3>
                  <p className="m-0 mt-1 text-xs text-content-muted">
                    Compare each caption with its photo. Correct factual mistakes and remove identity details;
                    edits save when you leave the field.
                  </p>
                </div>
                <DatasetGrid
                  images={images.filter((image) => image.status === 'keep' && image.filename)}
                  datasetId={d.id}
                  onStatus={ds.setStatus}
                  onCaption={ds.setCaption}
                  onCrop={setCropImg}
                  onDelete={ds.deleteImage}
                  onRegenerate={ds.regenerate}
                  onView={setViewImg}
                  onBatch={ds.batchImages}
                  busy={ds.busy}
                  nonces={ds.nonces}
                  faceThresholds={d.face_thresholds}
                  exclusiveImageIds={unresolvedExclusiveIds}
                  onLoadMore={ds.loadMoreImages}
                  reviewOnly
                />
              </section>
              {filtersActive && (
                <p className="m-0 text-content-subtle text-[0.6875rem]">
                  🔎 A tag filter is active — the filtered grid lives in{' '}
                  <button type="button" onClick={() => onStepChange('curate')}
                    className="underline hover:text-content">Curate images</button>
                  {' '}(showing {gridImages.length} of {images.length}).
                </p>
              )}
              </div>
            )}
          </div>

          <div className={stepCls('export')}>
            <div id="gf-export" className="scroll-mt-20 flex flex-col gap-2">
              <div className="flex flex-col gap-2 rounded-lg border border-border bg-surface px-3 py-2">
                <div id="ds-export-training-zip" tabIndex={-1}
                  className="flex items-center gap-2 flex-wrap scroll-mt-20">
                  <button type="button" data-workspace-focus={kept ? '' : undefined}
                    disabled={!kept} onClick={exportZipGuarded}
                    className="px-3 py-1.5 rounded-lg bg-gradient-primary text-white text-sm font-semibold disabled:opacity-40">
                    ⬇ Export ZIP ({kept})
                  </button>
                  <span className="text-content-subtle text-[0.6875rem]">
                    kept images + captions, training-ready (kohya layout)
                  </span>
                </div>
                {caps.hf_publish && kept > 0 && (
                  <div id="ds-export-hugging-face" tabIndex={-1}
                    className="flex items-center gap-2 flex-wrap scroll-mt-20">
                    <button type="button" data-workspace-focus
                      onClick={() => setPublishHfOpen(true)}
                      title="Publish this dataset (kept images + captions) as a dataset repo on the Hugging Face Hub. Private by default; you choose the license and confirm you have the right to share."
                      className="px-3 py-1.5 rounded-lg bg-surface border border-border text-content text-sm">
                      🤗 Publish to Hugging Face
                    </button>
                    <span className="text-content-subtle text-[0.6875rem]">
                      dataset repo on the Hub — private by default
                    </span>
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className={stepCls('backup')}>
            <div id="ds-export-backup" tabIndex={-1}
              className="flex flex-col gap-2 rounded-lg border border-border bg-surface px-3 py-3">
              <button type="button" data-workspace-focus onClick={() => {
                ds.exportBackup();
                setSessionCompletedSteps((current) => ({ ...current, backup: true }));
              }}
                title="Full portable backup: all images with statuses, captions, scores and settings — restore it on any machine from the Datasets page."
                className="self-start rounded-lg bg-gradient-primary px-4 py-2 text-sm font-semibold text-white">
                💾 Download portable backup
              </button>
              <p className="m-0 text-sm text-content-muted">
                Store this ZIP somewhere separate from the app. It preserves images, decisions,
                captions, scores, photo details, and dataset settings for restoration on another machine.
              </p>
            </div>
          </div>

          <div className={stepCls('train')}>
            <div id="gf-training" className="scroll-mt-20 flex flex-col gap-2">
              <div id="ds-training-launch" tabIndex={-1}
                className="flex flex-col gap-2 scroll-mt-20">
                {/* Pastille de préparation (miroir du preflight) : refreshKey borné aux
                    compteurs pertinents → pas de re-fetch à chaque poll du dataset. */}
                {caps.training_visible && (
                  <TrainingReadiness datasetId={d.id} trainType={d.train_type}
                    refreshKey={`${kept}|${keptCaptioned}|${pending}|${triage}|${d.caption_leak?.leaking ?? ''}`}
                    onJump={(targetId) => jumpTo({ targetId })} />
                )}
                <TrainingPanel ds={ds} keptCount={kept} kind={d.kind}
                  onCheckpointsChange={setCheckpointCount}
                  checkpointHost={checkpointHost}
                  navigationPanel={null}
                  onNavigationStateChange={NOOP} onPanelOpenChange={NOOP} />
              </div>
            </div>
          </div>

          {/* The TrainingPanel stays mounted exactly once; its checkpoint manager
              portals into this first-class stage so the queue poller is not duplicated. */}
          <div className={stepCls('checkpoints')}>
            <div id="gf-checkpoints" className="scroll-mt-20 flex flex-col gap-2">
              <div id="ds-checkpoints-manager" ref={setCheckpointHost} tabIndex={-1}
                className="scroll-mt-20" />
            </div>
          </div>

          {/* ============ 🎛️ Studio — final stage and dedicated-page launcher. */}
          <div className={stepCls('studio')}>
            <div id="gf-studio" className="scroll-mt-20 flex flex-col gap-2">
              {caps.studio_visible ? (
                <button id="ds-studio-launcher" type="button" data-workspace-focus
                  onClick={() => navigate(`/studio?dataset=${d.id}`)}
                  className="flex items-center gap-2 rounded-lg border border-purple-500/30 bg-purple-500/5 px-3 py-2.5 text-left hover:bg-purple-500/10 transition-colors scroll-mt-20">
                  <span aria-hidden>🎛️</span>
                  <span className="text-content font-semibold text-sm">LoRA testing studio</span>
                  {d.best_settings && (
                    <span className="text-amber-300 text-[0.6875rem]" title="Saved winning settings">
                      ★ {fmt(d.best_settings.strength)}
                    </span>
                  )}
                  <span className="ml-auto px-3 py-1.5 rounded-lg bg-gradient-primary text-white text-xs font-semibold">
                    ⤢ Open Studio
                  </span>
                </button>
              ) : (
                <p className="m-0 rounded-lg border border-border bg-surface px-3 py-2 text-content-muted text-sm">
                  Configure ComfyUI in Settings to use the LoRA testing Studio.
                </p>
              )}
            </div>
          </div>

          <DatasetStepActions current={activeStep} previous={previousWorkflowStep}
            next={nextWorkflowStep} onNavigate={onStepChange} />
        </div>{/* /right column */}
      </div>{/* /workspace grid */}

      {cropImg && cropImg.filename && (
        <CropModal imageUrl={datasetImageUrl(d.id, cropImg)}
          onCancel={() => setCropImg(null)}
          onConfirm={async (box) => { if (await ds.crop(cropImg.id, box)) setCropImg(null); }} />
      )}
      {refCrop && d.ref_filename && (
        // Feed the crop editor the full-frame ORIGINAL (when kept) so the box can widen
        // back out — not just tighten the already-cropped square. Legacy datasets with
        // no stored original fall back to the cropped ref (can only tighten, as before).
        <CropModal imageUrl={datasetImageUrl(d.id, d.ref_original_filename || d.ref_filename)}
          defaultAspect={1}
          onCancel={() => setRefCrop(false)}
          onConfirm={async (box) => { if (await ds.cropRef(box)) setRefCrop(false); }}
          onReset={d.ref_original_filename
            ? async () => { if (await ds.recropRefAuto()) setRefCrop(false); }
            : undefined} />
      )}
      {viewImgLive && (
        <DatasetLightbox img={viewImgLive} datasetId={d.id}
          nonce={(ds.nonces && ds.nonces[viewImgLive.id]) || 0}
          onClose={() => setViewImg(null)}
          onImprove={canImproveViewImg ? ds.improveImage : undefined}
          improvePending={viewImgImproving}
          improveReady={viewImgImprovementReady}
          busy={ds.busy}
          kleinAvailable={Boolean(caps.engines?.klein)}
          onCrop={viewImgLive._rescueReviewPreview || viewImgLive._imageImprovementReviewPreview
            ? undefined
            : (img) => { setViewImg(null); setCropImg(img); }} />
      )}
      {settingsOpen && (
        <DatasetSettingsModal d={d} busy={ds.busy}
          onSave={ds.updateSettings} onClose={() => setSettingsOpen(false)} />
      )}
      {publishHfOpen && (
        <PublishHfModal datasetId={d.id} onClose={() => setPublishHfOpen(false)} />
      )}
      {reviewQueue && reviewQueue.length > 0 && (
        <WatermarkReviewLightbox
          datasetId={d.id}
          queue={reviewQueue}
          caps={caps}
          nonces={ds.nonces}
          onSaveRegions={(id, regions) => ds.saveWatermarkRegions(id, regions)}
          onClean={(id) => ds.cleanWatermarkImages([id])}
          onDismiss={(id) => ds.dismissWatermarks([id])}
          onReject={(id) => ds.setStatus(id, 'reject')}
          onClose={(recap) => {
            setReviewQueue(null);
            if (recap) toast.success(`Review done — ${recap}`);
          }} />
      )}
    </div>
  );
}
