const FRAME_LABELS = { face: 'Face', bust: 'Bust', body: 'Body', back: 'Back' };
const STATE_LABELS = {
  covered: { icon: '✓', label: 'covered', cls: 'text-emerald-300 border-emerald-400/40 bg-emerald-500/10' },
  weak: { icon: '△', label: 'weak', cls: 'text-amber-300 border-amber-400/40 bg-amber-500/10' },
  missing: { icon: '!', label: 'missing', cls: 'text-rose-300 border-rose-400/40 bg-rose-500/10' },
  unknown: { icon: '?', label: 'unknown', cls: 'text-content-subtle border-border bg-app/50' },
};

function StateBadge({ state }) {
  const meta = STATE_LABELS[state] || STATE_LABELS.unknown;
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-1.5 py-px text-[0.625rem] ${meta.cls}`}>
      <span aria-hidden="true">{meta.icon}</span>{meta.label}
    </span>
  );
}

function CountChip({ label, value, tone = 'neutral' }) {
  const cls = tone === 'green'
    ? 'border-emerald-400/40 bg-emerald-500/10 text-emerald-300'
    : tone === 'amber'
      ? 'border-amber-400/40 bg-amber-500/10 text-amber-300'
      : 'border-border bg-app/50 text-content-muted';
  return (
    <span className={`rounded-full border px-2 py-0.5 text-[0.625rem] ${cls}`}>
      {label} <strong className="font-semibold text-content">{value}</strong>
    </span>
  );
}

export default function CoveragePlan({ plan, onGoToGenerate }) {
  if (!plan?.available) return null;
  const summary = plan.summary || {};
  const technical = plan.technical || {};
  const gaps = (plan.framing || []).filter((item) => item.deficit > 0);
  const unresolved = (plan.combinations || [])
    .filter((item) => item.state !== 'covered')
    .slice(0, 12);
  const recommended = plan.recommended_variation_ids || [];
  const dimensions = plan.dimensions || [];

  return (
    <section id="ds-coverage-plan" tabIndex={-1}
      className="flex flex-col gap-2 rounded-lg border border-indigo-400/40 bg-indigo-500/[0.06] px-3 py-2 scroll-mt-20">
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span aria-hidden="true">🧭</span>
            <h3 className="m-0 text-sm font-semibold text-content">Coverage plan</h3>
            <span className="rounded-full border border-indigo-400/40 bg-indigo-500/10 px-1.5 py-px text-[0.625rem] text-indigo-200">
              {summary.gaps || 0} framing gaps
            </span>
          </div>
          <p className="m-0 mt-0.5 text-[0.6875rem] leading-relaxed text-content-muted">
            The corpus stays authoritative. Generation is suggested only for empty framing buckets;
            imported photos without classification remain <em>unknown</em>, not falsely missing.
          </p>
        </div>
        {recommended.length > 0 && onGoToGenerate && (
          <button type="button" onClick={onGoToGenerate}
            className="ml-auto shrink-0 rounded-lg bg-gradient-primary px-3 py-1.5 text-xs font-semibold text-white">
            ⚡ Review {recommended.length} gap shots
          </button>
        )}
      </div>

      <div className="flex flex-wrap gap-1.5">
        <CountChip label="reference pool" value={summary.reference_pool || 0} tone="green" />
        <CountChip label="usable" value={summary.usable || 0} />
        <CountChip label="generated" value={summary.generated || 0} />
        <CountChip label="pending candidates" value={summary.pending_candidates || 0} />
        <CountChip label="originals preserved" value={summary.originals_preserved || 0} />
        <CountChip label="API anchors/request" value={plan.anchor_limit || 0} tone="amber" />
      </div>

      {gaps.length > 0 ? (
        <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
          {gaps.map((gap) => (
            <div key={gap.id} className="rounded-md border border-border bg-app/40 px-2 py-1.5">
              <div className="flex items-center justify-between gap-1">
                <span className="text-[0.6875rem] font-semibold text-content">{FRAME_LABELS[gap.framing] || gap.framing}</span>
                <StateBadge state={gap.state} />
              </div>
              <div className="mt-1 text-[0.625rem] text-content-muted">
                {gap.have}/{gap.target} · {gap.deficit} needed
              </div>
              <div className="mt-1 h-1 overflow-hidden rounded-full bg-app">
                <span className="block h-full rounded-full bg-amber-400"
                  style={{ width: `${Math.min(100, (gap.have / Math.max(1, gap.target)) * 100)}%` }} />
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="m-0 text-[0.6875rem] text-emerald-300">✓ Framing targets are covered.</p>
      )}

      {dimensions.length > 0 && (
        <div className="grid gap-1.5 sm:grid-cols-2 xl:grid-cols-3">
          {dimensions.map((dimension) => {
            const open = (dimension.items || []).filter((item) => item.state !== 'covered');
            return (
              <details key={dimension.id} className="rounded-md border border-border bg-app/30 px-2 py-1.5">
                <summary className="cursor-pointer text-[0.6875rem] font-semibold capitalize text-content-muted">
                  {dimension.id} · {dimension.classified} mapped
                  {open.length ? ` · ${open.length} gaps` : ' · covered'}
                </summary>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {(dimension.items || []).map((item) => (
                    <span key={item.id} className="inline-flex items-center gap-1 rounded-full border border-border bg-surface px-1.5 py-px text-[0.625rem] text-content-muted">
                      {item.value} {item.have}/{item.target} <StateBadge state={item.state} />
                    </span>
                  ))}
                </div>
                {dimension.unknown > 0 && (
                  <p className="m-0 mt-1 text-[0.5625rem] text-content-subtle">{dimension.unknown} accepted image(s) unknown on this axis</p>
                )}
              </details>
            );
          })}
        </div>
      )}

      {unresolved.length > 0 && (
        <details className="rounded-md border border-border bg-app/30 px-2 py-1.5">
          <summary className="cursor-pointer text-[0.6875rem] font-semibold text-content-muted">
            Combination detail · {summary.missing_combinations || 0} missing · {summary.unknown_combinations || 0} unknown
          </summary>
          <div className="mt-1.5 grid grid-cols-1 gap-1 sm:grid-cols-2">
            {unresolved.map((item) => (
              <div key={item.id} className="flex min-w-0 items-center justify-between gap-2 text-[0.625rem]">
                <span className="truncate text-content-muted">{item.label}</span>
                <StateBadge state={item.state} />
              </div>
            ))}
          </div>
          {recommended.length > 0 && (
            <p className="m-0 mt-1.5 text-[0.625rem] text-content-subtle">
              The gap plan preselects the first {recommended.length} genuinely empty combinations in the generator below.
            </p>
          )}
        </details>
      )}

      <div className="flex flex-wrap gap-2 text-[0.625rem] text-content-subtle">
        <span>Technical: {technical.green || 0} green · {technical.amber || 0} amber · {technical.red || 0} red</span>
        <span aria-hidden="true">·</span>
        <span>Unknown means “needs review/classification”, not “discard”.</span>
      </div>
    </section>
  );
}
