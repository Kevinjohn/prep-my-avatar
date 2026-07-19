function percent(value) {
  return value == null ? '—' : `${Math.round(Number(value) * 100)}%`;
}

const KIND_STYLE = {
  preserve: 'border-emerald-400/40 bg-emerald-500/10 text-emerald-100',
  dataset: 'border-amber-400/40 bg-amber-500/10 text-amber-100',
  compare: 'border-sky-400/40 bg-sky-500/10 text-sky-100',
};

export default function TrainingFeedbackPanel({ feedback, compact = false }) {
  if (!feedback) return null;
  const runs = feedback.runs || [];
  const recommendations = feedback.recommendations || [];
  const headingId = `training-feedback-${feedback.family || 'run'}-${compact ? 'compact' : 'full'}`;
  return (
    <section aria-labelledby={headingId}
      className="rounded-lg border border-indigo-400/30 bg-indigo-500/5 p-3 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id={headingId} className="m-0 text-sm font-semibold text-indigo-100">
          ↺ Training feedback loop
        </h3>
        <span className="rounded border border-border bg-surface px-1.5 py-px text-[0.625rem] uppercase text-content-muted">
          {feedback.family}
        </span>
      </div>
      <p className="mb-0 mt-1 text-content-muted">{feedback.summary}</p>

      {recommendations.length > 0 && (
        <ul className="mb-0 mt-2 grid list-none gap-1.5 p-0 sm:grid-cols-2">
          {recommendations.map((item, index) => (
            <li key={`${item.kind}-${index}`}
              className={`rounded-md border px-2 py-1.5 ${KIND_STYLE[item.kind] || 'border-border bg-surface text-content-muted'}`}>
              <strong className="block text-[0.6875rem]">{item.title}</strong>
              <span className="text-[0.625rem] opacity-90">{item.detail}</span>
            </li>
          ))}
        </ul>
      )}

      {runs.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer text-[0.6875rem] font-semibold text-content-muted">
            Evidence by training run ({runs.length})
          </summary>
          <div className="mt-1 overflow-x-auto">
            <table className="w-full min-w-[36rem] border-collapse text-left text-[0.625rem]">
              <thead className="text-content-subtle">
                <tr>
                  <th scope="col" className="py-1 pr-3">Run</th>
                  <th scope="col" className="py-1 pr-3">Recipe</th>
                  <th scope="col" className="py-1 pr-3">Tested</th>
                  <th scope="col" className="py-1 pr-3">Votes</th>
                  <th scope="col" className="py-1 pr-3">Approval</th>
                  <th scope="col" className="py-1 pr-3">Best tested point</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border text-content-muted">
                {runs.slice(0, compact ? 4 : 8).map((run) => (
                  <tr key={run.record_id}>
                    <th scope="row" className="py-1 pr-3 font-semibold text-content">
                      v{run.version} · {run.source}
                    </th>
                    <td className="py-1 pr-3">{run.steps ? `${run.steps} steps` : 'legacy/unknown'}</td>
                    <td className="py-1 pr-3 tabular-nums">{run.images}</td>
                    <td className="py-1 pr-3 tabular-nums">{run.likes}👍 {run.dislikes}👎</td>
                    <td className="py-1 pr-3 tabular-nums">
                      {percent(run.like_rate)} · {run.confidence}
                    </td>
                    <td className="py-1 pr-3 tabular-nums">
                      {run.best_step ? `step ${run.best_step}` : '—'}
                      {run.best_strength != null ? ` @ ${run.best_strength}` : ''}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </section>
  );
}
