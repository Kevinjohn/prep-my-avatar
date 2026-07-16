import { useMemo, useState } from 'react';
import { buildImageImprovementPairs } from '../../utils/imageImprovement';

function url(datasetId, image, displayFilename) {
  const filename = displayFilename || image?.filename;
  return filename
    ? `/api/dataset/${datasetId}/img/${encodeURIComponent(filename)}` : null;
}

function Pane({ datasetId, image, label, onPreview, displayFilename, faceOverride, identityOverride }) {
  const imageUrl = url(datasetId, image, displayFilename);
  const face = faceOverride !== undefined ? (faceOverride || {}) : (image?.analysis?.face || {});
  const metrics = image?.analysis?.metrics || {};
  const identity = identityOverride !== undefined ? identityOverride : image?.face_score;
  const previewImage = {
    ...image,
    filename: displayFilename || image?.filename,
    _imageImprovementReviewPreview: true,
  };
  return (
    <div className="min-w-0 overflow-hidden rounded-lg border border-border bg-app/50">
      <div className="flex items-center justify-between border-b border-border px-2 py-1">
        <span className="text-[0.6875rem] font-semibold text-content">{label}</span>
        <span className="text-[0.625rem] text-content-subtle">{image?.status}</span>
      </div>
      <div className="aspect-square bg-black">
        {imageUrl ? (
          <button type="button" onClick={() => onPreview?.(previewImage)}
            className="block h-full w-full cursor-zoom-in" aria-label={`Inspect ${label}`}>
            <img src={imageUrl} alt={label} className="h-full w-full object-contain" />
          </button>
        ) : (
          <div className="flex h-full items-center justify-center text-xs text-content-subtle">
            {image?.status === 'failed' ? '⚠ reconstruction failed' : '⏳ reconstructing…'}
          </div>
        )}
      </div>
      <div className="grid grid-cols-2 gap-1 border-t border-border p-2 text-[0.625rem] text-content-muted">
        <span>technical <b className="text-content">{image?.training_usefulness || 'unknown'}</b></span>
        <span>face pixels <b className="text-content">{face.quality || 'unchecked'}</b></span>
        <span>sharpness <b className="text-content">{metrics.sharpness ?? '—'}</b></span>
        <span>identity <b className="text-content">{identity?.toFixed?.(3) ?? '—'}</b></span>
      </div>
    </div>
  );
}

const RECOMMENDATIONS = {
  identity_risk: ['text-rose-300', 'Identity score fell — prefer the original unless visual inspection clearly disagrees.'],
  quality_risk: ['text-rose-300', 'The reconstructed face does not have a clean face-pixel QA result.'],
  no_measured_gain: ['text-amber-200', 'No measurable technical gain; extra synthetic pixels add little value.'],
  manual_identity_check: ['text-amber-200', 'Identity could not be compared automatically; inspect closely.'],
  manual_quality_check: ['text-amber-200', 'Technical quality could not be compared automatically; inspect at 100%.'],
  candidate_improved: ['text-emerald-300', 'Measured quality improved without a material identity-score loss.'],
};

export default function ImageImprovementReview({ images, datasetId, onResolve, onPreview }) {
  const pairs = useMemo(
    () => buildImageImprovementPairs(images).filter((pair) => !pair.resolved), [images]);
  const [resolving, setResolving] = useState(() => new Set());
  if (!pairs.length) return null;

  const choose = async (candidateId, choice) => {
    if (resolving.has(candidateId)) return;
    setResolving((current) => new Set(current).add(candidateId));
    try { await onResolve(candidateId, choice); }
    finally {
      setResolving((current) => {
        const next = new Set(current); next.delete(candidateId); return next;
      });
    }
  };

  return (
    <section className="flex flex-col gap-3 rounded-xl border border-cyan-400/40 bg-cyan-500/[0.05] p-3">
      <div>
        <h3 className="m-0 text-sm font-semibold text-content">🔬 Reconstruction review</h3>
        <p className="m-0 mt-0.5 text-[0.6875rem] text-content-subtle">
          This is generative reconstruction, not neutral upscaling. Compare at full size; one atomic choice admits exactly one version to training.
        </p>
      </div>
      {pairs.map(({ original, candidate, phase }) => {
        const comparison = candidate.analysis?.repair_comparison || {};
        const recommendation = RECOMMENDATIONS[comparison.recommendation];
        const qaPhase = comparison.phase || (phase === 'ready' ? 'analyzing' : phase);
        const sourceFilename = comparison.source_filename
          || original.original_filename || original.filename;
        const busy = resolving.has(candidate.id);
        return (
          <article key={candidate.id} className="rounded-lg border border-border bg-surface p-2.5">
            <div className="grid grid-cols-2 gap-2">
              <Pane datasetId={datasetId} image={original} label="Exact reconstruction input"
                displayFilename={sourceFilename} faceOverride={comparison.source_face}
                identityOverride={comparison.source_identity_score} onPreview={onPreview} />
              <Pane datasetId={datasetId} image={candidate} label="Reconstructed candidate" onPreview={onPreview} />
            </div>
            <div className="mt-2 rounded border border-border bg-app/40 px-2 py-1.5 text-[0.6875rem]">
              {phase === 'queued' && <span className="text-cyan-200">Reconstruction in progress…</span>}
              {phase === 'failed' && <span className="text-rose-300">{candidate.fail_reason || 'Reconstruction failed.'}</span>}
              {phase === 'ready' && qaPhase === 'analyzing' && (
                <span className="text-cyan-200">Automatic identity and face-pixel QA is running…</span>
              )}
              {phase === 'ready' && qaPhase === 'failed' && (
                <span className="text-rose-300">Automatic comparison failed: {comparison.qa_error || 'unknown QA error'}. Inspect both versions manually.</span>
              )}
              {phase === 'ready' && qaPhase === 'ready' && recommendation && (
                <span className={recommendation[0]}>{recommendation[1]}{' '}
                  Technical Δ {comparison.technical_delta ?? '—'} · identity Δ {comparison.identity_delta ?? '—'}
                </span>
              )}
              {phase === 'ready' && qaPhase === 'ready' && comparison.qa_error && (
                <span className="mt-1 block text-amber-200">QA note: {comparison.qa_error}</span>
              )}
            </div>
            <div className="mt-2 grid gap-2 sm:grid-cols-3">
              <button type="button" disabled={busy} onClick={() => choose(candidate.id, 'original')}
                className="rounded-lg border border-border bg-surface-raised px-2 py-1.5 text-xs font-semibold text-content disabled:opacity-40">Keep source</button>
              <button type="button" disabled={busy || phase !== 'ready'}
                onClick={() => choose(candidate.id, 'improved')}
                className="rounded-lg border border-cyan-400/50 bg-cyan-500/15 px-2 py-1.5 text-xs font-semibold text-cyan-100 disabled:opacity-40">Use reconstruction</button>
              <button type="button" disabled={busy} onClick={() => choose(candidate.id, 'reject')}
                className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-2 py-1.5 text-xs font-semibold text-rose-300 disabled:opacity-40">Reject both</button>
            </div>
          </article>
        );
      })}
    </section>
  );
}
