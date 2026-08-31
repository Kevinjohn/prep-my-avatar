import { useEffect, useMemo, useRef, useState } from 'react';
import { isCleanAdmissionCandidate, needsQualityReview } from '../../utils/corpusAdmission.js';
import {
  technicalAnalysisCounts,
  technicalAnalysisState,
} from '../../utils/technicalAnalysis.js';
import CorpusPhotoTable from './CorpusPhotoTable';
import { FRAMING_ORDER } from './variationCatalogModel';

const COVERAGE_OPTIONS = {
  // 'unknown' is a corpus-only bucket: an imported photo nobody has classified yet.
  framing: [...FRAMING_ORDER, 'unknown'],
  angle: ['front', 'three-quarter', 'profile', 'back', 'other'],
  expression: ['neutral', 'smile', 'laugh', 'serious', 'surprised', 'pensive', 'other'],
  lighting: ['daylight', 'indoor', 'studio', 'golden-hour', 'low-light', 'mixed', 'other'],
  pose: ['standing', 'sitting', 'moving', 'headshot', 'other'],
  background: ['plain', 'indoor', 'outdoor', 'studio', 'crowded', 'other'],
  occlusion: ['none', 'minor', 'major'],
};

const FILTERS = [
  ['all', 'All'], ['pending', 'Needs decision'], ['quality', 'Quality review'],
  ['anchors', 'Generation photos'], ['duplicates', 'Duplicates'], ['unclassified', 'Needs details'],
];
const EMPTY_IDS = new Set();

function countClassified(image) {
  return Object.keys(image?.coverage || {}).length;
}

function Stat({ label, value, tone = '' }) {
  const cls = tone === 'good' ? 'text-emerald-200'
    : tone === 'warn' ? 'text-amber-200' : 'text-content-muted';
  return <span className={`text-[0.625rem] ${cls}`}>{label} <b>{value}</b></span>;
}

export default function CorpusWorkbench({ datasetId, images = [], anchorPlan = null, coveragePlan,
  onAnalyze, onClassify = null, onAnchorDecision = null, onCoverage = null,
  onSourceRights, onStatus, onBatch = null,
  busy = false, visionAvailable = false, visionUnavailableReason = 'Local vision is not ready',
  reviewPairIds = EMPTY_IDS,
  faceThresholds = { green: 0.50 },
  showAnchors = true, showCoverage = true, mode = 'all' }) {
  const reviewVisible = mode === 'all' || mode === 'review';
  const anchorsVisible = mode === 'anchors' || (mode === 'all' && showAnchors);
  const coverageVisible = mode === 'coverage' || (mode === 'all' && showCoverage);
  const filters = mode === 'anchors'
    ? FILTERS.filter(([id]) => ['all', 'anchors', 'duplicates'].includes(id))
    : mode === 'coverage'
      ? FILTERS.filter(([id]) => ['all', 'unclassified'].includes(id))
      : mode === 'review'
        ? FILTERS.filter(([id]) => ['all', 'pending', 'quality', 'duplicates'].includes(id))
        : FILTERS;
  const imported = useMemo(() => images.filter((image) => image.source === 'import'
    && image.filename && !reviewPairIds.has(image.id)), [images, reviewPairIds]);
  const analysisCounts = useMemo(() => technicalAnalysisCounts(imported), [imported]);
  const selectedIds = useMemo(() => new Set(anchorPlan?.selected_import_ids || []), [anchorPlan]);
  const duplicateRoots = useMemo(() => new Set(imported.map((image) => image.duplicate_of_id).filter(Boolean)), [imported]);
  const [filter, setFilter] = useState('all');
  const [selectedId, setSelectedId] = useState(null);
  const selected = imported.find((image) => image.id === selectedId) || imported[0] || null;
  const [draft, setDraft] = useState({});
  const [rightsDraft, setRightsDraft] = useState({ basis: 'unknown', license: '', consent_confirmed: false, notes: '' });
  const [draftDirty, setDraftDirty] = useState(false);
  const [rightsDirty, setRightsDirty] = useState(false);
  const previousSelectedId = useRef(null);

  useEffect(() => {
    if (!selected) { setSelectedId(null); setDraft({}); previousSelectedId.current = null; return; }
    if (selected.id !== selectedId) setSelectedId(selected.id);
    const selectionChanged = previousSelectedId.current !== selected.id;
    previousSelectedId.current = selected.id;
    if (selectionChanged || !draftDirty) setDraft({ framing: selected.framing || '', ...(selected.coverage || {}) });
    if (selectionChanged || !rightsDirty) setRightsDraft({ basis: selected.source_rights?.basis || 'unknown',
      license: selected.source_rights?.license || '',
      consent_confirmed: Boolean(selected.source_rights?.consent_confirmed),
      notes: selected.source_rights?.notes || '' });
    if (selectionChanged) { setDraftDirty(false); setRightsDirty(false); }
    // Sync only when the selected server row changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.id, selected?.framing, selected?.coverage, selected?.source_rights, draftDirty, rightsDirty]);

  if (!imported.length) {
    return (
      <section id="ds-corpus-review" tabIndex={-1}
        className="scroll-mt-20 rounded-lg border border-dashed border-border bg-surface px-3 py-4 text-center">
        <h3 className="m-0 text-sm font-semibold text-content">Photo review</h3>
        <p className="m-0 mt-1 text-xs text-content-subtle">Import your real photos first; they will appear here for review, generation-photo selection, and photo-variety checks.</p>
      </section>
    );
  }

  const visible = imported.filter((image) => {
    if (filter === 'pending') return image.status === 'pending';
    if (filter === 'quality') return needsQualityReview(image);
    if (filter === 'anchors') return selectedIds.has(image.id) || image.anchor_decision === 'pinned';
    if (filter === 'duplicates') return !!image.duplicate_of_id || duplicateRoots.has(image.id);
    if (filter === 'unclassified') return !image.framing || image.framing === 'unknown' || countClassified(image) < 6;
    return true;
  });
  const summary = coveragePlan?.summary || {};
  const pending = imported.filter((image) => image.status === 'pending');
  const accepted = imported.filter((image) => image.status === 'keep');
  const identityFloor = Number(faceThresholds.green ?? 0.50);
  const cleanPending = pending.filter((image) => (
    isCleanAdmissionCandidate(image, identityFloor, duplicateRoots)
  ));
  const redPending = pending.filter((image) => image.training_usefulness === 'red'
    || image.analysis?.face?.quality === 'red');
  const selectedAnalysis = technicalAnalysisState(selected?.analysis);
  const refreshTitle = `Re-runs CPU-local technical analysis with bokeh-aware sharpness scoring. ${
    analysisCounts.outdated} outdated and ${analysisCounts.missing} not analyzed. `
    + 'Face analysis, photo details, rights, and review decisions are preserved.';

  return (
    <section id="ds-corpus-review" tabIndex={-1}
      className="scroll-mt-20 flex flex-col gap-3">
      <div className="flex flex-wrap items-start gap-2">
        <p className="m-0 max-w-2xl text-[0.6875rem] leading-relaxed text-content-muted">
          Import preserves the master photo pool. Only images you accept here enter training; rejected and undecided originals remain available for review.
        </p>
        <div data-corpus-actions className="ml-auto flex max-w-xl flex-col items-start gap-1 sm:items-end">
          <div className="flex flex-wrap items-center gap-1.5 sm:justify-end">
            <button type="button" onClick={onAnalyze} disabled={busy} title={refreshTitle}
              className="rounded-lg border border-border bg-surface-raised px-2.5 py-1.5 text-xs font-semibold text-content disabled:opacity-40">
              📐 Refresh local analysis{analysisCounts.outdated
                ? ` (${analysisCounts.outdated} outdated)` : ''}
            </button>
            {coverageVisible && (visionAvailable ? (
                <button type="button" onClick={onClassify} disabled={busy}
                  title="Classify framing, angle, expression, lighting, pose and background"
                  className="rounded-lg border border-indigo-400/40 bg-indigo-500/10 px-2.5 py-1.5 text-xs font-semibold text-indigo-200 disabled:opacity-40">
                  👁 Analyse photo variety
                </button>
              ) : (
                <a href="#/setup" aria-describedby={`photo-variety-unavailable-${datasetId}`}
                  className="rounded-lg border border-indigo-400/40 bg-indigo-500/10 px-2.5 py-1.5 text-xs font-semibold text-indigo-200 hover:bg-indigo-500/20">
                  👁 Analyse photo variety
                </a>
              ))}
          </div>
          {coverageVisible && !visionAvailable && (
            <p id={`photo-variety-unavailable-${datasetId}`}
              className="m-0 text-[0.625rem] leading-relaxed text-amber-200 sm:text-right">
              {visionUnavailableReason}
            </p>
          )}
        </div>
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1 border-y border-border py-2">
        <Stat label="real photos" value={imported.length} tone="good" />
        <Stat label="accepted for training" value={accepted.length} tone={accepted.length ? 'good' : 'warn'} />
        <Stat label="needs decision" value={pending.length} tone={pending.length ? 'warn' : 'good'} />
        {anchorsVisible && <Stat label="photos per request" value={`${anchorPlan?.selected_total || 0}/${anchorPlan?.limit || 0}`} />}
        {anchorsVisible && <Stat label="always included" value={anchorPlan?.pinned || 0} />}
        {anchorsVisible && <Stat label="never sent" value={anchorPlan?.excluded || 0} />}
        <Stat label="near-duplicates" value={summary.near_duplicates || 0} tone={summary.near_duplicates ? 'warn' : ''} />
        <Stat label="needs photo details" value={summary.unclassified || 0} tone={summary.unclassified ? 'warn' : 'good'} />
        {!!analysisCounts.outdated && <Stat label="outdated analysis" value={analysisCounts.outdated} tone="warn" />}
        {!!analysisCounts.missing && <Stat label="not analyzed" value={analysisCounts.missing} tone="warn" />}
      </div>

      {reviewVisible && !!pending.length && onBatch && (
        <div className="flex flex-wrap items-center gap-2 border-y border-amber-400/30 py-2">
          <span className="text-[0.6875rem] text-amber-100">Admission shortcuts only act on undecided photos with completed QA.</span>
          <button type="button" disabled={busy || !cleanPending.length}
            onClick={() => onBatch(cleanPending.map((image) => image.id), 'keep')}
            className="rounded-md border border-emerald-400/40 bg-emerald-500/10 px-2 py-1 text-[0.625rem] font-semibold text-emerald-200 disabled:opacity-40">
            ✓ Accept clean ({cleanPending.length})
          </button>
          <button type="button" disabled={busy || !redPending.length}
            onClick={() => onBatch(redPending.map((image) => image.id), 'reject')}
            className="rounded-md border border-red-400/40 bg-red-500/10 px-2 py-1 text-[0.625rem] font-semibold text-red-200 disabled:opacity-40">
            ✕ Reject red QA ({redPending.length})
          </button>
        </div>
      )}

      <div className="flex flex-wrap gap-1" role="group" aria-label="Photo filters">
        {filters.map(([id, label]) => (
          <button key={id} type="button" onClick={() => setFilter(id)} aria-pressed={filter === id}
            className={`border-b-2 px-1 py-1 text-[0.625rem] ${filter === id
              ? 'border-indigo-400 text-indigo-200'
              : 'border-transparent text-content-muted hover:text-content'}`}>
            {label}
          </button>
        ))}
        <span className="ml-auto self-center text-[0.625rem] text-content-subtle">showing {visible.length}/{imported.length}</span>
      </div>

      <div className="grid min-h-0 gap-3 lg:grid-cols-[minmax(0,1.35fr)_minmax(300px,0.65fr)] lg:gap-0">
        <CorpusPhotoTable datasetId={datasetId} images={visible}
          selectedId={selected?.id} selectedIds={selectedIds} duplicateRoots={duplicateRoots}
          anchorsVisible={anchorsVisible} onSelect={setSelectedId} />

        {selected && (
          <aside data-photo-editor aria-label="Selected photo details"
            className="flex flex-col gap-3 border-t border-border pt-3 lg:border-l lg:border-t-0 lg:pl-3 lg:pt-0">
            <div className="min-w-0">
              <p className="m-0 truncate text-xs font-semibold text-content" title={selected.source_name || ''}>
                {selected.source_name || `Imported image ${selected.id}`}
              </p>
              <p className="m-0 mt-0.5 text-[0.625rem] text-content-subtle">
                technical {selected.training_usefulness || 'unknown'}
                {` · analysis ${selectedAnalysis.label}`}
                {selected.analysis?.face?.quality ? ` · face pixels ${selected.analysis.face.quality}` : ' · face pixels not checked'}
                {selected.face_state === 'scorable' && selected.face_score != null
                  ? ` · identity ${selected.face_score.toFixed(3)}`
                  : ` · identity ${selected.face_state || 'not checked'}`}
                {selected.duplicate_of_id ? ` · near-duplicate of #${selected.duplicate_of_id}` : ''}
              </p>
            </div>

            {reviewVisible && <div>
              <p className="m-0 mb-1 text-[0.625rem] font-semibold uppercase tracking-wide text-content-muted">Training admission</p>
              <div className="grid grid-cols-3 gap-1">
                {[['keep', '✓ Accept'], ['pending', '… Review'], ['reject', '✕ Reject']].map(([value, label]) => (
                  <button key={value} type="button" disabled={busy}
                    onClick={() => onStatus(selected.id, value)} aria-pressed={selected.status === value}
                    className={`rounded-md border px-1.5 py-1 text-[0.625rem] ${selected.status === value
                      ? 'border-indigo-400/60 bg-indigo-500/20 text-indigo-100'
                      : 'border-border bg-surface text-content-muted'}`}>
                    {label}
                  </button>
                ))}
              </div>
            </div>}

            {anchorsVisible && <div>
              <p className="m-0 mb-1 text-[0.625rem] font-semibold uppercase tracking-wide text-content-muted">Use for generation</p>
              <div className="grid grid-cols-3 gap-1">
                {[['auto', 'Automatic'], ['pinned', '📌 Always use'], ['excluded', '⊘ Never send']].map(([value, label]) => (
                  <button key={value} type="button" disabled={busy}
                    onClick={() => onAnchorDecision(selected.id, value)}
                    aria-pressed={(selected.anchor_decision || 'auto') === value}
                    className={`rounded-md border px-1.5 py-1 text-[0.625rem] ${(selected.anchor_decision || 'auto') === value
                      ? 'border-indigo-400/60 bg-indigo-500/20 text-indigo-100'
                      : 'border-border bg-surface text-content-muted'}`}>
                    {label}
                  </button>
                ))}
              </div>
              <p className="m-0 mt-1 text-[0.5625rem] leading-relaxed text-content-subtle">
                Excluding affects API identity references only; the photo can still remain in the training set.
              </p>
            </div>}

            {reviewVisible && <form aria-label="Source rights and consent"
              className="flex flex-col gap-1.5 border-t border-border pt-3"
              onSubmit={async (event) => {
                event.preventDefault();
                const saved = await onSourceRights?.(selected.id, rightsDraft);
                if (saved !== false) setRightsDirty(false);
              }}>
              <p className="m-0 text-[0.625rem] font-semibold uppercase tracking-wide text-content-muted">Source rights & consent</p>
              <div className="grid grid-cols-2 gap-1.5">
                <label className="flex flex-col gap-0.5 text-[0.5625rem] uppercase text-content-subtle">
                  basis
                  <select value={rightsDraft.basis}
                    onChange={(event) => { setRightsDirty(true); setRightsDraft((current) => ({ ...current, basis: event.target.value })); }}
                    className="rounded border border-border bg-surface px-1.5 py-1 text-[0.625rem] normal-case text-content">
                    {['unknown', 'owned', 'licensed', 'consented', 'public-domain'].map((value) => (
                      <option key={value} value={value}>{value}</option>
                    ))}
                  </select>
                </label>
                <label className="flex flex-col gap-0.5 text-[0.5625rem] uppercase text-content-subtle">
                  license / terms
                  <input value={rightsDraft.license}
                    onChange={(event) => { setRightsDirty(true); setRightsDraft((current) => ({ ...current, license: event.target.value })); }}
                    className="rounded border border-border bg-surface px-1.5 py-1 text-[0.625rem] normal-case text-content" />
                </label>
              </div>
              <label className="flex items-center gap-1.5 text-[0.625rem] text-content-muted">
                <input type="checkbox" checked={rightsDraft.consent_confirmed}
                  onChange={(event) => { setRightsDirty(true); setRightsDraft((current) => ({ ...current, consent_confirmed: event.target.checked })); }} />
                Identifiable-person consent confirmed
              </label>
              <textarea value={rightsDraft.notes} rows={2} placeholder="Source URL, contract, or consent note"
                onChange={(event) => { setRightsDirty(true); setRightsDraft((current) => ({ ...current, notes: event.target.value })); }}
                className="rounded border border-border bg-surface px-1.5 py-1 text-[0.625rem] text-content" />
              <button type="submit" disabled={busy || !onSourceRights}
                className="rounded-md border border-indigo-400/40 bg-indigo-500/10 px-2 py-1 text-[0.625rem] font-semibold text-indigo-200 disabled:opacity-40">
                Save rights record
              </button>
            </form>}

            {coverageVisible && <form className="grid grid-cols-2 gap-1.5" onSubmit={async (event) => {
              event.preventDefault();
              const saved = await onCoverage(selected.id, draft);
              if (saved !== false) setDraftDirty(false);
            }}>
              {Object.entries(COVERAGE_OPTIONS).map(([key, options]) => (
                <label key={key} className="flex min-w-0 flex-col gap-0.5 text-[0.5625rem] uppercase tracking-wide text-content-subtle">
                  {key}
                  <select value={draft[key] || ''}
                    onChange={(event) => { setDraftDirty(true); setDraft((current) => ({ ...current, [key]: event.target.value })); }}
                    className="min-w-0 rounded border border-border bg-surface px-1.5 py-1 text-[0.625rem] normal-case tracking-normal text-content">
                    <option value="">unknown</option>
                    {options.map((option) => <option key={option} value={option}>{option}</option>)}
                  </select>
                </label>
              ))}
              <button type="submit" disabled={busy}
                className="col-span-2 mt-1 rounded-lg bg-gradient-primary px-2.5 py-1.5 text-xs font-semibold text-white disabled:opacity-40">
                Save photo details
              </button>
              {selected.coverage_provenance && (
                <p className="col-span-2 m-0 text-[0.5625rem] text-content-subtle">
                  Evidence: {selected.coverage_provenance.source || 'unknown'}
                  {selected.coverage_provenance.model ? ` · ${selected.coverage_provenance.model}` : ''}
                </p>
              )}
            </form>}
          </aside>
        )}
      </div>
    </section>
  );
}
