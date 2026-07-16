import { useEffect, useState } from 'react';

const LS_KEY = 'guidedCardCollapsed';

const COPY = {
  corpus: 'Import as many real photos as you have. The fork analyses them before suggesting generated gap-filling shots.',
  review: 'Map framing, angle, expression, lighting, pose and background; near-duplicates stay visible for your decision.',
  anchors: 'Review the bounded API anchor set. Pin identity-critical photos or exclude any image that must never be sent to a provider.',
  reference: 'Optionally choose one primary reference for local Klein generation; API engines use the reviewed anchor set.',
  coverage: 'Review what your corpus covers, distinguish real gaps from unknowns, then use the suggested shots.',
  generate: 'Generate only the missing coverage combinations from the reference (or keep importing real photos).',
  curate: 'Review the grid: keep ✓ the good ones, reject ✕ the rest.',
  caption: 'Caption the kept images — required for training.',
  finish_export: 'Your dataset is ready — export the ZIP for training.',
  finish_train: 'Your dataset is ready — launch a LoRA training.',
  studio: 'Compare checkpoints in the Test Studio and pick the best one.',
};

export default function NextStepCard({ step, trainMode, busy, totalImages, onAction, actionLabel }) {
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(LS_KEY) === '1');
  const forceOpen = totalImages === 0;
  const open = forceOpen || !collapsed;
  useEffect(() => { if (!forceOpen) localStorage.setItem(LS_KEY, collapsed ? '1' : '0'); },
    [collapsed, forceOpen]);
  if (!step) return null;
  const key = step.id === 'finish' ? (trainMode ? 'finish_train' : 'finish_export') : step.id;

  return (
    <div role="status" className="rounded-lg border border-indigo-400/40 bg-indigo-500/10 px-3 py-2">
      <div className="flex items-center gap-2">
        <span aria-hidden>💡</span>
        <span className="text-content text-sm font-semibold">Next step: {step.label}</span>
        {!forceOpen && (
          <button type="button" onClick={() => setCollapsed((v) => !v)} aria-expanded={open}
            className="ml-auto text-content-subtle hover:text-content px-1"
            title={open ? 'Collapse the guide' : 'Expand the guide'}>
            <span aria-hidden>{open ? '▾' : '▸'}</span>
            <span className="sr-only">{open ? 'Collapse' : 'Expand'} next-step guide</span>
          </button>
        )}
      </div>
      {open && (
        <div className="mt-1 flex items-center gap-3 flex-wrap">
          <p className="text-content-muted text-sm m-0">{COPY[key]}</p>
          <button type="button" onClick={onAction} disabled={busy}
            className="ml-auto px-3 py-1.5 rounded-lg bg-gradient-primary text-white text-sm font-semibold disabled:opacity-40">
            {actionLabel}
          </button>
        </div>
      )}
    </div>
  );
}
