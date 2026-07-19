import { useEffect, useRef, useState } from 'react';

import { safeJson } from '../../api/fetchClient';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import { useBodyScrollLock } from '../../hooks/useBodyScrollLock';

const FAMILY_LABEL = {
  zimage: 'Z-Image',
  krea: 'Krea 2',
  sdxl: 'SDXL',
  flux: 'FLUX.1',
  flux2klein: 'FLUX.2 Klein',
};

function formatDuration(minutes) {
  if (minutes == null) return '—';
  if (minutes < 90) return `~${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return remainder ? `~${hours} h ${remainder} min` : `~${hours} h`;
}

/** Launch-time speed picker backed by current cloud offers and cost estimates. */
export default function CloudLaunchDialog({
  datasetId,
  trainType,
  steps,
  keptCount,
  cloudStatus,
  onClose,
  onLaunch,
}) {
  const dialogRef = useRef(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [data, setData] = useState(null);
  const [selected, setSelected] = useState(null);
  const [launching, setLaunching] = useState(false);
  useFocusTrap(dialogRef, true);
  useBodyScrollLock(true);

  useEffect(() => {
    let alive = true;
    (async () => {
      const qs = new URLSearchParams({ train_type: trainType });
      if (steps) qs.set('steps', String(steps));
      const body = await safeJson(
        `/api/dataset/${datasetId}/train/cloud/offers?${qs.toString()}`,
      );
      if (!alive) return;
      if (body.ok === false) {
        setError(body.error || body.hint || `Could not load offers (HTTP ${body.status})`);
      } else {
        setData(body);
        if (body.tiers?.length) setSelected(body.tiers[0].gpu_name);
      }
      setLoading(false);
    })();
    return () => { alive = false; };
  }, [datasetId, trainType, steps]);

  const launch = async () => {
    if (!selected) return;
    setLaunching(true);
    try {
      const started = await onLaunch(selected);
      if (started) onClose();
    } finally {
      setLaunching(false);
    }
  };

  const tiers = data?.tiers || [];
  const budget = cloudStatus?.monthly_budget || 0;
  const spent = cloudStatus?.month_spend || 0;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="cloud-gpu-dialog-title"
      className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4"
      onKeyDown={(event) => { if (event.key === 'Escape' && !launching) onClose(); }}
    >
      <div ref={dialogRef} className="w-full max-w-lg rounded-xl border border-border bg-surface-overlay p-4 flex flex-col gap-3">
        <h3 id="cloud-gpu-dialog-title" className="m-0 text-content font-bold text-sm">
          <span aria-hidden>☁️</span> Choose GPU speed for this run
        </h3>

        {loading && <p className="m-0 text-content-muted text-sm">Loading live GPU offers…</p>}
        {error && <p role="alert" className="m-0 text-red-300 text-sm">⚠ {error}</p>}
        {!loading && !error && tiers.length === 0 && (
          <p className="m-0 text-content-muted text-sm">
            No GPU available under ${data?.max_price_per_hour}/h right now — raise the
            price cap in Settings, or try again shortly.
          </p>
        )}

        {tiers.length > 0 && (
          <div className="flex flex-col gap-1.5 max-h-[50vh] overflow-y-auto">
            {tiers.map((tier) => (
              <label
                key={tier.gpu_name}
                className={`flex items-center gap-3 rounded-lg border px-3 py-2 cursor-pointer transition-colors ${
                  selected === tier.gpu_name
                    ? 'border-sky-400/70 bg-sky-500/10'
                    : 'border-border bg-surface hover:bg-surface-raised'}`}
              >
                <input
                  type="radio"
                  name="gpu-tier"
                  className="accent-sky-400"
                  checked={selected === tier.gpu_name}
                  onChange={() => setSelected(tier.gpu_name)}
                />
                <span className="flex-1 min-w-0">
                  <span className="block text-content text-sm font-semibold truncate">
                    {tier.gpu_name}
                    {tier.gpu_ram_gb ? <span className="text-content-subtle font-normal"> · {tier.gpu_ram_gb} GB</span> : null}
                  </span>
                  <span className="block text-content-subtle text-[0.75rem] tabular-nums">
                    {tier.dph_total != null ? `$${tier.dph_total.toFixed(3)}/h` : 'price n/a'}
                    {' · '}{formatDuration(tier.est_minutes)}
                    {tier.est_cost != null ? ` · ≈ $${tier.est_cost.toFixed(2)} total` : ''}
                  </span>
                  {tier.exceeds_cap && (
                    <span className="block text-amber-300 text-[0.6875rem]">
                      ⚠ Longer than the {Math.round((data?.max_runtime_minutes || 480) / 60)} h runtime cap — the run would be cut short (checkpoint rescued). Pick a faster GPU or raise the cap in Settings.
                    </span>
                  )}
                </span>
              </label>
            ))}
          </div>
        )}

        <p className="m-0 text-content-subtle text-[0.6875rem]">
          {(data?.steps ?? steps ?? '—')} steps · {FAMILY_LABEL[data?.family || trainType] || (data?.family || trainType)}
          {keptCount != null ? ` · ${keptCount} img` : ''}
          {budget > 0 ? ` · this month: $${spent.toFixed(2)} of $${budget.toFixed(2)}` : ''}
          {'. '}Time & cost are approximate; the pod is auto-terminated when done.
        </p>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={launch}
            disabled={!selected || launching}
            className="px-3 py-1.5 rounded-lg bg-gradient-primary text-white text-sm font-semibold disabled:opacity-40"
          >
            {launching ? 'Launching…' : '☁️ Rent & train'}
          </button>
          <button
            type="button"
            onClick={onClose}
            disabled={launching}
            className="ml-auto px-3 py-1.5 rounded-lg text-content-muted hover:text-content text-sm disabled:opacity-40"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
