import { FRAMING_LABEL } from './variationCatalogModel';
import { coverageResolution } from './coverageResolutionModel';

function pluralize(count, singular) {
  return `${singular}${count === 1 ? '' : 's'}`;
}

export default function CoverageGapResolution({ plan, onGoToGenerate, onAcknowledgeGaps }) {
  const { actions, unresolved, acknowledged, requiresAttention } = coverageResolution(plan);
  const recommendations = (plan.recommendations || [])
    .filter((item) => item.kind === 'generate');

  if (!actions.length && !acknowledged) {
    return (
      <p role="status" className="m-0 rounded-md border border-emerald-400/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
        ✓ Required photo-variety targets are covered.
      </p>
    );
  }

  return (
    <section aria-labelledby="coverage-resolution-title"
      className={`rounded-md border px-3 py-2 ${requiresAttention
        ? 'border-amber-400/50 bg-amber-500/[0.08]'
        : 'border-emerald-400/30 bg-emerald-500/[0.06]'}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h4 id="coverage-resolution-title" className="m-0 text-xs font-semibold text-content">
            Primary gaps to resolve
          </h4>
          <p className="m-0 mt-0.5 text-[0.6875rem] text-content-muted">
            These are dataset targets. One well-chosen photo can also cover several secondary gaps.
          </p>
        </div>
        <span className={`rounded-full border px-2 py-0.5 text-[0.625rem] ${acknowledged
          ? 'border-emerald-400/40 text-emerald-300'
          : 'border-amber-400/50 text-amber-300'}`}>
          {acknowledged ? 'Accepted for this dataset' : `${unresolved} need a decision`}
        </span>
      </div>

      <ol className="mb-0 mt-2 grid list-decimal gap-2 pl-5 sm:grid-cols-2 lg:grid-cols-3">
        {actions.map((action) => (
          <li key={action.framing} className="text-[0.6875rem] text-content-muted">
            <strong className="text-content">
              Add {action.deficit} {FRAMING_LABEL[action.framing] || action.framing} {pluralize(action.deficit, 'photo')}
            </strong>
            <span className="ml-1 text-content-subtle">({action.have}/{action.target})</span>
            {action.suggested_shots?.length > 0 && (
              <span className="mt-0.5 block text-content-subtle">
                Suggested: {action.suggested_shots.join(' · ')}
              </span>
            )}
          </li>
        ))}
      </ol>

      {recommendations.length > 0 && (
        <details className="mt-2 border-t border-border pt-2">
          <summary className="cursor-pointer text-[0.6875rem] font-semibold text-content-muted">
            Exact recommended shot plan · {recommendations.length} shots
          </summary>
          <ol className="mb-0 mt-1.5 grid list-decimal gap-1 pl-5 sm:grid-cols-2">
            {recommendations.map((item) => (
              <li key={item.variation_id} className="text-[0.625rem] text-content-muted">
                <strong className="font-medium text-content">{item.shot_label}</strong>
                <span className="ml-1 text-content-subtle">— {FRAMING_LABEL[item.framing] || item.framing}</span>
              </li>
            ))}
          </ol>
        </details>
      )}

      <div className="mt-2 flex flex-wrap gap-2 border-t border-border pt-2">
        {recommendations.length > 0 && onGoToGenerate && (
          <button type="button" onClick={onGoToGenerate}
            className="rounded-lg bg-gradient-primary px-3 py-1.5 text-xs font-semibold text-white">
            Review {recommendations.length} gap shots →
          </button>
        )}
        {requiresAttention && (
          <button type="button" onClick={() => onAcknowledgeGaps?.(plan.gap_signature)}
            disabled={!onAcknowledgeGaps}
            className="rounded-lg border border-amber-400/40 bg-amber-500/10 px-3 py-1.5 text-xs font-semibold text-amber-200 disabled:opacity-40">
            Accept remaining gaps
          </button>
        )}
        {acknowledged && (
          <button type="button" onClick={() => onAcknowledgeGaps?.(null)} disabled={!onAcknowledgeGaps}
            className="rounded-lg border border-border bg-surface px-3 py-1.5 text-xs text-content-muted disabled:opacity-40">
            Reopen this decision
          </button>
        )}
      </div>
    </section>
  );
}
