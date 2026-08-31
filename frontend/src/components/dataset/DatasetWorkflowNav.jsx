function stepState(step, currentSlug) {
  if (step.slug === currentSlug) return { glyph: '●', label: 'Current' };
  if (step.done) return { glyph: '✓', label: 'Complete' };
  if (step.unavailable) return { glyph: '!', label: 'Unavailable' };
  if (step.optional) return { glyph: '○', label: 'Optional' };
  return { glyph: '○', label: 'Upcoming' };
}

export default function DatasetWorkflowNav({ steps, currentSlug, onNavigate }) {
  const currentIndex = Math.max(0, steps.findIndex((step) => step.slug === currentSlug));
  return (
    <nav aria-label="Dataset steps">
      <div className="lg:hidden">
        <label className="flex flex-col gap-1 text-xs text-content-muted">
          <span>Step {currentIndex + 1} of {steps.length}</span>
          <select value={currentSlug} onChange={(event) => onNavigate(event.target.value)}
            className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-content">
            {steps.map((step, index) => {
              const state = stepState(step, currentSlug);
              return (
                <option key={step.slug} value={step.slug}>
                  {index + 1}. {step.label} — {state.label}
                </option>
              );
            })}
          </select>
        </label>
      </div>

      <div className="hidden border-r border-border pr-3 lg:block">
        <p className="m-0 px-1.5 pb-1.5 text-[0.6875rem] font-semibold uppercase tracking-wide text-content-subtle">
          Dataset steps
        </p>
        <ol className="m-0 flex list-none flex-col gap-0.5 p-0">
          {steps.map((step, index) => {
            const current = step.slug === currentSlug;
            const state = stepState(step, currentSlug);
            const tone = current ? 'border-indigo-400 text-content font-semibold'
              : step.done ? 'text-emerald-300'
                : step.unavailable ? 'text-content-subtle'
                  : 'text-content-muted hover:text-content';
            return (
              <li key={step.slug}>
                <button type="button" onClick={() => onNavigate(step.slug)}
                  aria-current={current ? 'step' : undefined}
                  className={`flex w-full items-start gap-2 border-l-2 px-2 py-1.5 text-left text-xs ${current ? tone : `border-transparent ${tone}`}`}>
                  <span aria-hidden className="w-4 shrink-0 text-center">{state.glyph}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[0.8125rem]">
                      <span className="mr-1 text-content-muted">{index + 1}.</span>
                      {step.label}
                    </span>
                    <span className="block text-[0.625rem] font-normal text-content-muted">
                      {state.label}
                      {step.unavailableReason ? ` — ${step.unavailableReason}` : ''}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      </div>
    </nav>
  );
}

export function DatasetStepActions({ current, previous, next, onNavigate }) {
  return (
    <nav aria-label="Step actions"
      className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-3">
      {previous ? (
        <button type="button" onClick={() => onNavigate(previous.slug)}
          className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-content-muted hover:bg-surface-raised hover:text-content">
          ← Back <span className="hidden sm:inline">to {previous.label}</span>
        </button>
      ) : <span />}
      <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
        {current.optional && next && (
          <button type="button" onClick={() => onNavigate(next.slug)}
            className="rounded-lg px-3 py-2 text-sm text-content-muted underline hover:text-content">
            Skip optional step
          </button>
        )}
        {next && (
          <button type="button" onClick={() => onNavigate(next.slug)}
            className="rounded-lg bg-gradient-primary px-4 py-2 text-sm font-semibold text-white">
            Continue <span className="hidden sm:inline">to {next.label}</span> →
          </button>
        )}
      </div>
    </nav>
  );
}
