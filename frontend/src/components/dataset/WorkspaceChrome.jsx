export function GridFilterBar({
  excludes,
  includes,
  shown,
  total,
  onRemoveExclude,
  onRemoveInclude,
  onClearAll,
}) {
  return (
    <div
      role="status"
      className="flex items-center gap-2 flex-wrap rounded-lg border-2 border-amber-400/50 bg-amber-400/10 px-3 py-2"
    >
      <span className="text-amber-200 text-sm font-semibold shrink-0">🔎 Filtered view</span>
      <span className="text-content-muted text-xs tabular-nums shrink-0">
        showing {shown} of {total}
      </span>
      <div className="flex items-center gap-1.5 flex-wrap">
        {excludes.map((tag) => (
          <span
            key={`x-${tag}`}
            className="inline-flex items-center gap-1 rounded-full border border-rose-400/50 bg-rose-500/15 pl-2 pr-1 py-0.5 text-[0.6875rem] text-rose-200"
          >
            <span aria-hidden>⊘</span> {tag}
            <button
              type="button"
              onClick={() => onRemoveExclude(tag)}
              aria-label={`Stop hiding images tagged ${tag}`}
              className="w-4 h-4 grid place-items-center rounded-full hover:bg-rose-500/30"
            >✕</button>
          </span>
        ))}
        {includes.map((tag) => (
          <span
            key={`i-${tag}`}
            className="inline-flex items-center gap-1 rounded-full border border-indigo-400/50 bg-indigo-500/15 pl-2 pr-1 py-0.5 text-[0.6875rem] text-indigo-200"
          >
            <span aria-hidden>◉</span> only {tag}
            <button
              type="button"
              onClick={() => onRemoveInclude(tag)}
              aria-label={`Stop isolating images tagged ${tag}`}
              className="w-4 h-4 grid place-items-center rounded-full hover:bg-indigo-500/30"
            >✕</button>
          </span>
        ))}
      </div>
      <button
        type="button"
        onClick={onClearAll}
        className="ml-auto shrink-0 text-content-muted underline hover:text-content text-xs"
      >
        clear all
      </button>
    </div>
  );
}
