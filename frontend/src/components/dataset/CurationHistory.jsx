import { useCallback, useEffect, useState } from 'react';
import { apiFetch } from '../../api/fetchClient';

const LABELS = {
  caption: 'Caption edited',
  coverage: 'Coverage corrected',
};

function actionLabel(action) {
  if (LABELS[action]) return LABELS[action];
  const [kind, value] = String(action || '').split(':');
  if (kind === 'status') return `Marked ${value}`;
  if (kind === 'anchor') return `Anchor set to ${value}`;
  if (kind === 'batch') return `Batch marked ${value}`;
  if (kind === 'small_rescue') return `Rescue choice: ${value}`;
  if (kind === 'image_improvement') return `Reconstruction choice: ${value}`;
  return String(action || 'Curation change').replaceAll('_', ' ');
}

export default function CurationHistory({ datasetId, refreshKey, onUndo }) {
  const [history, setHistory] = useState({ events: [], can_undo: false });
  const [loading, setLoading] = useState(true);
  const [undoing, setUndoing] = useState(false);

  const load = useCallback(async () => {
    try {
      const result = await apiFetch(`/api/dataset/${datasetId}/curation/history?limit=8`);
      setHistory(result);
    } catch { /* the workspace keeps working if history is temporarily unavailable */ }
    finally { setLoading(false); }
  }, [datasetId]);

  useEffect(() => { setLoading(true); load(); }, [load, refreshKey]);

  const undo = async (eventId) => {
    setUndoing(true);
    try {
      const ok = await onUndo(eventId);
      if (ok) await load();
    } finally { setUndoing(false); }
  };
  const batches = history.events.reduce((result, event) => {
    const existing = result.find((item) => item.batch_id === event.batch_id);
    if (existing) existing.visible_image_ids.push(event.image_id);
    else result.push({ ...event, visible_image_ids: [event.image_id] });
    return result;
  }, []);

  return (
    <details className="rounded-lg border border-border bg-surface px-3 py-2">
      <summary className="cursor-pointer select-none text-sm font-semibold text-content">
        ↶ Curation history
        <span className="ml-2 text-[0.6875rem] font-normal text-content-subtle">
          {loading ? 'loading…' : `${history.events.length} recent change(s)`}
        </span>
      </summary>
      <div className="mt-2 flex flex-col gap-2">
        {!loading && history.events.length === 0 && (
          <p className="m-0 text-xs text-content-subtle">No manual curation changes yet.</p>
        )}
        <ol className="m-0 flex list-none flex-col gap-1 p-0" aria-label="Recent curation changes">
          {batches.map((event) => (
            <li key={event.id}
              className="flex items-center gap-2 rounded-md border border-border px-2 py-1.5 text-xs">
              <span className={event.reverted ? 'text-content-subtle line-through' : 'text-content'}>
                {actionLabel(event.action)} · {event.batch_size > 1
                  ? `${event.batch_size} images (atomic batch)`
                  : `image ${event.image_id}`}
              </span>
              {!event.reverted && (
                <button type="button" disabled={undoing}
                  onClick={() => undo(event.id)}
                  className="ml-auto rounded border border-border px-2 py-0.5 text-content-subtle hover:text-content disabled:opacity-40"
                  aria-label={event.batch_size > 1
                    ? `Undo ${actionLabel(event.action)} for the entire ${event.batch_size}-image batch`
                    : `Undo ${actionLabel(event.action)} for image ${event.image_id}`}>
                  {event.batch_size > 1 ? 'Undo batch' : 'Undo'}
                </button>
              )}
            </li>
          ))}
        </ol>
        {history.can_undo && (
          <button type="button" disabled={undoing} onClick={() => undo(undefined)}
            className="self-start rounded-md border border-indigo-400/40 bg-indigo-500/10 px-2.5 py-1 text-xs text-indigo-200 disabled:opacity-40">
            {undoing ? 'Undoing…' : '↶ Undo latest change'}
          </button>
        )}
        <p className="m-0 text-[0.6875rem] text-content-subtle">
          Each row is one atomic action; batch actions undo together. Undo stops if a newer edit would be overwritten.
        </p>
      </div>
    </details>
  );
}
