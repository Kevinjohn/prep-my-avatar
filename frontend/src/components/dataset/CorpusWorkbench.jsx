import { useEffect, useMemo, useState } from 'react';

const COVERAGE_OPTIONS = {
  framing: ['face', 'bust', 'body', 'back', 'unknown'],
  angle: ['front', 'three-quarter', 'profile', 'back', 'other'],
  expression: ['neutral', 'smile', 'laugh', 'serious', 'surprised', 'pensive', 'other'],
  lighting: ['daylight', 'indoor', 'studio', 'golden-hour', 'low-light', 'mixed', 'other'],
  pose: ['standing', 'sitting', 'moving', 'headshot', 'other'],
  background: ['plain', 'indoor', 'outdoor', 'studio', 'crowded', 'other'],
  occlusion: ['none', 'minor', 'major'],
};

const FILTERS = [
  ['all', 'All'], ['anchors', 'Anchor set'], ['duplicates', 'Duplicates'],
  ['unclassified', 'Needs coverage'],
];

function countClassified(image) {
  return Object.keys(image?.coverage || {}).length;
}

function decisionLabel(image, selectedIds) {
  if (image.anchor_decision === 'pinned') return 'pinned';
  if (image.anchor_decision === 'excluded') return 'excluded';
  return selectedIds.has(image.id) ? 'auto-selected' : 'automatic';
}

function Stat({ label, value, tone = '' }) {
  const cls = tone === 'good' ? 'border-emerald-400/40 bg-emerald-500/10 text-emerald-200'
    : tone === 'warn' ? 'border-amber-400/40 bg-amber-500/10 text-amber-200'
      : 'border-border bg-app/50 text-content-muted';
  return <span className={`rounded-full border px-2 py-0.5 text-[0.625rem] ${cls}`}>{label} <b>{value}</b></span>;
}

export default function CorpusWorkbench({ datasetId, images = [], anchorPlan, coveragePlan,
  onAnalyze, onClassify, onAnchorDecision, onCoverage, busy = false,
  visionAvailable = false }) {
  const imported = useMemo(() => images.filter((image) => image.source === 'import' && image.filename), [images]);
  const selectedIds = useMemo(() => new Set(anchorPlan?.selected_import_ids || []), [anchorPlan]);
  const duplicateRoots = useMemo(() => new Set(imported.map((image) => image.duplicate_of_id).filter(Boolean)), [imported]);
  const [filter, setFilter] = useState('all');
  const [selectedId, setSelectedId] = useState(null);
  const selected = imported.find((image) => image.id === selectedId) || imported[0] || null;
  const [draft, setDraft] = useState({});

  useEffect(() => {
    if (!selected) { setSelectedId(null); setDraft({}); return; }
    if (selected.id !== selectedId) setSelectedId(selected.id);
    setDraft({ framing: selected.framing || '', ...(selected.coverage || {}) });
    // Sync only when the selected server row changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.id, selected?.framing, selected?.coverage]);

  if (!imported.length) {
    return (
      <section id="ds-corpus-review" tabIndex={-1}
        className="scroll-mt-20 rounded-lg border border-dashed border-border bg-surface px-3 py-4 text-center">
        <h3 className="m-0 text-sm font-semibold text-content">Corpus workbench</h3>
        <p className="m-0 mt-1 text-xs text-content-subtle">Import your real photos first; they will appear here for coverage and anchor review.</p>
      </section>
    );
  }

  const visible = imported.filter((image) => {
    if (filter === 'anchors') return selectedIds.has(image.id) || image.anchor_decision === 'pinned';
    if (filter === 'duplicates') return !!image.duplicate_of_id || duplicateRoots.has(image.id);
    if (filter === 'unclassified') return !image.framing || image.framing === 'unknown' || countClassified(image) < 6;
    return true;
  });
  const summary = coveragePlan?.summary || {};

  return (
    <section id="ds-corpus-review" tabIndex={-1}
      className="scroll-mt-20 flex flex-col gap-3 rounded-xl border border-border bg-surface p-3">
      <div className="flex flex-wrap items-start gap-2">
        <div>
          <div className="flex items-center gap-2">
            <span aria-hidden>🗂️</span>
            <h3 className="m-0 text-sm font-semibold text-content">Corpus workbench</h3>
          </div>
          <p className="m-0 mt-0.5 max-w-3xl text-[0.6875rem] leading-relaxed text-content-muted">
            Keep the whole real-photo pool, resolve near-duplicates deliberately, and control which images may leave the machine as generation anchors.
          </p>
        </div>
        <div className="ml-auto flex flex-wrap gap-1.5">
          <button type="button" onClick={onAnalyze} disabled={busy}
            className="rounded-lg border border-border bg-surface-raised px-2.5 py-1.5 text-xs font-semibold text-content disabled:opacity-40">
            📐 Refresh local analysis
          </button>
          <button type="button" onClick={onClassify} disabled={busy || !visionAvailable}
            title={visionAvailable ? 'Classify framing, angle, expression, lighting, pose and background' : 'Set up Ollama vision, or classify images manually below'}
            className="rounded-lg border border-indigo-400/40 bg-indigo-500/10 px-2.5 py-1.5 text-xs font-semibold text-indigo-200 disabled:opacity-40">
            👁 Map visual coverage
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
        <Stat label="real photos" value={imported.length} tone="good" />
        <Stat label="anchors/request" value={`${anchorPlan?.selected_total || 0}/${anchorPlan?.limit || 0}`} />
        <Stat label="pinned" value={anchorPlan?.pinned || 0} />
        <Stat label="excluded from API" value={anchorPlan?.excluded || 0} />
        <Stat label="near-duplicates" value={summary.near_duplicates || 0} tone={summary.near_duplicates ? 'warn' : ''} />
        <Stat label="needs coverage" value={summary.unclassified || 0} tone={summary.unclassified ? 'warn' : 'good'} />
      </div>

      <div className="flex flex-wrap gap-1" role="tablist" aria-label="Corpus filters">
        {FILTERS.map(([id, label]) => (
          <button key={id} type="button" onClick={() => setFilter(id)} aria-pressed={filter === id}
            className={`rounded-md border px-2 py-1 text-[0.625rem] ${filter === id
              ? 'border-indigo-400/50 bg-indigo-500/15 text-indigo-200'
              : 'border-border bg-app/40 text-content-muted'}`}>
            {label}
          </button>
        ))}
        <span className="ml-auto self-center text-[0.625rem] text-content-subtle">showing {visible.length}/{imported.length}</span>
      </div>

      <div className="grid min-h-0 gap-3 lg:grid-cols-[minmax(0,1.35fr)_minmax(300px,0.65fr)]">
        <div className="grid max-h-[30rem] grid-cols-3 gap-1.5 overflow-auto pr-1 sm:grid-cols-5 xl:grid-cols-6">
          {visible.map((image) => {
            const active = selected?.id === image.id;
            const decision = decisionLabel(image, selectedIds);
            return (
              <button key={image.id} type="button" onClick={() => setSelectedId(image.id)}
                aria-pressed={active} title={image.source_name || `Imported image ${image.id}`}
                className={`relative aspect-square overflow-hidden rounded-lg border text-left ${active
                  ? 'border-indigo-300 ring-2 ring-indigo-400/40'
                  : 'border-border hover:border-content-subtle'}`}>
                <img loading="lazy" alt="" src={`/api/dataset/${datasetId}/img/${encodeURIComponent(image.filename)}`}
                  className="h-full w-full object-cover" />
                <span className={`absolute left-1 top-1 rounded bg-black/75 px-1 py-px text-[0.5625rem] ${decision === 'pinned'
                  ? 'text-emerald-300' : decision === 'excluded' ? 'text-rose-300' : 'text-white/80'}`}>
                  {decision === 'pinned' ? '📌 pinned' : decision === 'excluded' ? '⊘ API' : selectedIds.has(image.id) ? '◆ anchor' : 'auto'}
                </span>
                {(image.duplicate_of_id || duplicateRoots.has(image.id)) && (
                  <span className="absolute right-1 top-1 rounded bg-amber-950/90 px-1 py-px text-[0.5625rem] text-amber-200">≈ duplicate</span>
                )}
                <span className="absolute bottom-1 left-1 rounded bg-black/75 px-1 py-px text-[0.5625rem] text-white/75">
                  {image.framing || '?'} · {image.training_usefulness || 'unknown'}
                </span>
              </button>
            );
          })}
        </div>

        {selected && (
          <div className="flex flex-col gap-2 rounded-lg border border-border bg-app/40 p-2.5">
            <div className="min-w-0">
              <p className="m-0 truncate text-xs font-semibold text-content" title={selected.source_name || ''}>
                {selected.source_name || `Imported image ${selected.id}`}
              </p>
              <p className="m-0 mt-0.5 text-[0.625rem] text-content-subtle">
                technical {selected.training_usefulness || 'unknown'}
                {selected.duplicate_of_id ? ` · near-duplicate of #${selected.duplicate_of_id}` : ''}
              </p>
            </div>

            <div>
              <p className="m-0 mb-1 text-[0.625rem] font-semibold uppercase tracking-wide text-content-muted">Generation anchor</p>
              <div className="grid grid-cols-3 gap-1">
                {[['auto', 'Automatic'], ['pinned', '📌 Pin'], ['excluded', '⊘ Exclude']].map(([value, label]) => (
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
            </div>

            <form className="grid grid-cols-2 gap-1.5" onSubmit={async (event) => {
              event.preventDefault();
              await onCoverage(selected.id, draft);
            }}>
              {Object.entries(COVERAGE_OPTIONS).map(([key, options]) => (
                <label key={key} className="flex min-w-0 flex-col gap-0.5 text-[0.5625rem] uppercase tracking-wide text-content-subtle">
                  {key}
                  <select value={draft[key] || ''}
                    onChange={(event) => setDraft((current) => ({ ...current, [key]: event.target.value }))}
                    className="min-w-0 rounded border border-border bg-surface px-1.5 py-1 text-[0.625rem] normal-case tracking-normal text-content">
                    <option value="">unknown</option>
                    {options.map((option) => <option key={option} value={option}>{option}</option>)}
                  </select>
                </label>
              ))}
              <button type="submit" disabled={busy}
                className="col-span-2 mt-1 rounded-lg bg-gradient-primary px-2.5 py-1.5 text-xs font-semibold text-white disabled:opacity-40">
                Save coverage
              </button>
            </form>
          </div>
        )}
      </div>
    </section>
  );
}
