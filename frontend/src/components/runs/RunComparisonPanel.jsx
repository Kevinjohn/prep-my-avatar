const FAMILY_LABEL = {
  zimage: 'Z-Image', krea: 'Krea 2', sdxl: 'SDXL', flux: 'FLUX.1', flux2klein: 'FLUX.2 Klein',
};

function duration(seconds) {
  if (!Number.isFinite(Number(seconds))) return '—';
  const value = Math.max(0, Math.round(Number(seconds)));
  const h = Math.floor(value / 3600);
  const m = Math.floor((value % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}

function dateTime(iso) {
  if (!iso) return '—';
  const parsed = new Date(/[Z+]/.test(iso) ? iso : `${iso}Z`);
  return Number.isNaN(parsed.getTime()) ? '—' : parsed.toLocaleString();
}

function recipe(run) {
  const settings = run.settings || {};
  const items = [
    settings.rank ? `rank ${settings.rank}${settings.alpha ? `/${settings.alpha}` : ''}` : null,
    Array.isArray(settings.resolution) ? `${settings.resolution.join('+')} px` : null,
    settings.optimizer || null,
    settings.lr_scheduler || null,
    settings.dropout ? `dropout ${settings.dropout}` : null,
    settings.timestep_type || null,
  ].filter(Boolean);
  return items.length ? items.join(' · ') : 'Not recorded';
}

function admission(run) {
  const preflight = run.preflight || {};
  const verdict = preflight.verdict || preflight.status
    || (preflight.blockers?.length ? 'blocked' : preflight.warnings?.length ? 'warning' : 'recorded');
  const overrides = Object.entries(run.overrides || {}).filter(([, value]) => Boolean(value));
  return `${verdict}${overrides.length ? ` · overrides: ${overrides.map(([key]) => key).join(', ')}` : ' · no overrides'}`;
}

function evidence(run) {
  const item = run.evaluation;
  if (!item?.images) return 'Not Studio-tested';
  if (!item.voted) return `${item.images} tested · no votes`;
  return `${item.likes}👍 ${item.dislikes}👎 · ${Math.round(item.like_rate * 100)}% · ${item.confidence}`
    + (item.best_step ? ` · best step ${item.best_step}` : '')
    + (item.best_strength != null ? ` @ ${item.best_strength}` : '');
}

function cost(run) {
  if (run.source !== 'cloud') return 'Local · provider cost n/a';
  const amount = Number(run.cost_usd ?? run.cost_estimate);
  if (!Number.isFinite(amount)) return 'Not recorded';
  return `$${amount.toFixed(2)} ${run.cost_final ? 'final' : 'so far'}`
    + (run.price_per_hour != null ? ` · $${run.price_per_hour}/h` : '');
}

const ROWS = [
  ['Dataset', (run) => run.dataset_name || `#${run.dataset_id}`],
  ['Run identity', (run) => `${FAMILY_LABEL[run.train_type] || run.train_type || 'LoRA'} · v${run.version || '?'} · ${run.source}`],
  ['Started', (run) => dateTime(run.created_at)],
  ['Outcome', (run) => `${run.status || 'recorded'}${run.error ? ` · ${run.error}` : ''}`],
  ['Target', (run) => `${run.steps ?? '—'} steps${run.masked === false ? ' · unmasked' : ' · masked'}`],
  ['Dataset fingerprint', (run) => run.fingerprint || 'Not recorded'],
  ['Effective recipe', recipe],
  ['Admission', admission],
  ['Studio evidence', evidence],
  ['Provider cost', cost],
  ['Billed duration', (run) => duration(run.billing_seconds)],
  ['Training duration', (run) => duration(run.training_seconds)],
];

export default function RunComparisonPanel({ runs, onRemove, onClear }) {
  if (!runs.length) return null;
  const eligible = runs.filter((run) => (run.evaluation?.voted || 0) >= 3);
  const winner = eligible.length > 1
    ? [...eligible].sort((a, b) => (b.evaluation.wilson - a.evaluation.wilson)
      || (b.evaluation.voted - a.evaluation.voted))[0]
    : null;
  return (
    <section aria-labelledby="run-comparison-title"
      className="rounded-xl border border-indigo-400/35 bg-indigo-500/5 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="run-comparison-title" className="m-0 text-sm font-semibold text-indigo-100">
          Run comparison ({runs.length}/4)
        </h2>
        <button type="button" onClick={onClear}
          className="ml-auto rounded border border-border bg-surface px-2 py-1 text-xs text-content-muted">
          Clear comparison
        </button>
      </div>
      {runs.length < 2 ? (
        <p className="mb-0 mt-2 text-xs text-content-muted">Select one more recent run to compare it side by side.</p>
      ) : (
        <>
          {winner ? (
            <p className="mb-2 mt-2 rounded border border-emerald-400/35 bg-emerald-500/10 px-2 py-1 text-xs text-emerald-100">
              Strongest measured evidence: <b>{winner.dataset_name || `#${winner.dataset_id}`} v{winner.version}</b>
              {' '}({winner.evaluation.likes}/{winner.evaluation.voted} liked). This is evidence-ranked, not an automatic deployment decision.
            </p>
          ) : (
            <p className="mb-2 mt-2 rounded border border-amber-400/35 bg-amber-500/10 px-2 py-1 text-xs text-amber-100">
              No winner is declared until at least two selected runs have three linked Studio votes each.
            </p>
          )}
          <div className="overflow-x-auto">
            <table className="w-full min-w-[44rem] border-collapse text-left text-xs">
              <thead>
                <tr className="border-b border-border text-content-subtle">
                  <th scope="col" className="w-36 py-2 pr-3">Metric</th>
                  {runs.map((run) => (
                    <th scope="col" key={run._compareKey} className="min-w-48 py-2 pr-3 text-content">
                      <span className="flex items-center gap-1">
                        {run.dataset_name || `Dataset #${run.dataset_id}`} · v{run.version || '?'}
                        <button type="button" onClick={() => onRemove(run._compareKey)}
                          aria-label={`Remove ${run.dataset_name || `dataset ${run.dataset_id}`} version ${run.version || 'unknown'} from comparison`}
                          className="ml-auto rounded px-1 text-content-subtle hover:text-content">×</button>
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {ROWS.map(([label, render]) => (
                  <tr key={label}>
                    <th scope="row" className="py-2 pr-3 align-top font-semibold text-content-subtle">{label}</th>
                    {runs.map((run) => (
                      <td key={run._compareKey} className="py-2 pr-3 align-top text-content-muted break-words">
                        {render(run)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
