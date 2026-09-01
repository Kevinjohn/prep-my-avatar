import { useEffect, useRef, useState } from 'react';
import { safeJson } from '../../api/fetchClient';

/* Pastille de préparation à l'entraînement — miroir du preflight serveur
   (GET /train/preflight, champs checks+verdict) : 🟢 ready / 🟡 warnings /
   🔴 blocked, avec la liste des contrôles dépliable. Chaque ligne en défaut
   qui cible une section du workspace porte un bouton « Fix → » (onJump).
   Re-fetch débouncé quand les compteurs pertinents changent (curation,
   captions, fuites) — pas à chaque poll (le preflight relit les images sur
   disque pour le dHash). Rendu nul tant que rien n'est chargé ou si le
   backend gate (ai-toolkit absent → 409). */

const VERDICT = {
  ready: { icon: '🟢', label: 'Ready to train', cls: 'border-emerald-400/40 bg-emerald-500/10' },
  warnings: { icon: '🟡', label: 'Almost ready', cls: 'border-amber-400/40 bg-amber-500/10' },
  blocked: { icon: '🔴', label: 'Not ready', cls: 'border-red-400/40 bg-red-500/10' },
};
const ROW_ICON = { ok: '✓', warn: '⚠', fail: '✕' };
const ROW_CLS = { ok: 'text-emerald-400', warn: 'text-amber-300', fail: 'text-red-300' };

export default function TrainingReadiness({ datasetId, trainType, refreshKey, onJump }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(false);
  const [open, setOpen] = useState(false);
  const timer = useRef(null);
  useEffect(() => {
    let alive = true;
    // Débounce : les compteurs bougent en rafale pendant une passe de caption.
    clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      const qs = trainType ? `?train_type=${encodeURIComponent(trainType)}` : '';
      const d = await safeJson(`/api/dataset/${datasetId}/train/preflight${qs}`);
      if (!alive) return;
      if (d.ok === false) { setError(true); return; }
      if (d.ok) { setData(d); setError(false); }
    }, 400);
    return () => { alive = false; clearTimeout(timer.current); };
  }, [datasetId, trainType, refreshKey]);

  if (!data && error) return (
    <p role="alert" className="m-0 rounded-lg border border-red-400/40 bg-red-500/10 px-3 py-2 text-red-200 text-sm">
      Training readiness could not be refreshed. Launch controls remain unavailable until the check succeeds.
    </p>
  );
  if (!data || !(data.checks || []).length) return null;
  const v = VERDICT[data.verdict] || VERDICT.warnings;
  const warns = data.checks.filter((c) => c.status === 'warn').length;
  const fails = data.checks.filter((c) => c.status === 'fail').length;
  const firstBlocker = data.checks.find((c) => c.status === 'fail');
  const subtitle = data.verdict === 'ready'
    ? `${data.checks.length} checks passed`
    : [fails && `${fails} blocker(s)`, warns && `${warns} warning(s)`].filter(Boolean).join(' · ');

  return (
    <div className={`rounded-lg border ${v.cls}`}>
      {error && (
        <p role="alert" className="m-0 border-b border-amber-400/30 px-3 py-2 text-amber-200 text-xs">
          Refresh failed; showing the last successful readiness report. Launch controls remain unavailable.
        </p>
      )}
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="w-full flex items-center gap-2 px-3 py-2 text-left">
        <span aria-hidden>{v.icon}</span>
        <span className="text-content text-sm font-semibold">{v.label}</span>
        <span className="text-content-subtle text-[0.6875rem]">{subtitle}</span>
        <span aria-hidden className="ml-auto text-content-subtle text-xs">{open ? '▾' : '▸'}</span>
      </button>
      {!open && firstBlocker && (
        <p role="alert" className="m-0 px-3 pb-2.5 text-xs text-red-200">
          <span className="font-semibold">{firstBlocker.label}</span>
          <span className="text-red-200/80"> — {firstBlocker.detail}</span>
        </p>
      )}
      {open && (
        <ul className="m-0 px-3 pb-2.5 flex flex-col gap-1 list-none">
          {data.checks.map((c) => (
            <li key={c.id} className="flex items-start gap-2 text-[0.75rem]">
              <span aria-hidden className={`w-4 shrink-0 text-center font-bold ${ROW_CLS[c.status]}`}>
                {ROW_ICON[c.status]}
              </span>
              <span className="text-content">{c.label}</span>
              <span className="text-content-subtle">— {c.detail}</span>
              {c.status !== 'ok' && c.target && (
                <button type="button" onClick={() => onJump?.(c.target)}
                  className="ml-auto shrink-0 px-1.5 py-0.5 rounded border border-border text-content-muted hover:text-content hover:bg-surface-raised text-[0.6875rem]">
                  Fix →
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
