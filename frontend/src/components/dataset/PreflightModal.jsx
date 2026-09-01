/** Interactive pre-training preflight. Keeps the aggregate warning message but
 * drills into WHICH captions leak identity (editable in place, saves on blur)
 * WHICH kept images have pixel-QA warnings, and WHICH are near-duplicates — so the
 * offenders get fixed right at the confirm, not hunted down in the grid after.
 * Replaces the old blocking window.confirm: onResolve(true) = start anyway,
 * onResolve(false) = cancel. */
import { useRef, useState } from 'react';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import { useBodyScrollLock } from '../../hooks/useBodyScrollLock';
import { useEscapeToClose } from '../../hooks/useEscapeToClose';
import { datasetImageUrl } from './datasetImageUrl';

export default function PreflightModal({ report, datasetId, ds, onResolve }) {
  const {
    warnings = [],
    leak_images: leaks = [],
    dup_pairs: dups = [],
    quality_images: qualityImages = [],
  } = report || {};
  const leakGuidance = report?.leak_kind === 'concept'
    ? 'Captions naming the trained concept — remove the concept terms'
    : report?.leak_kind === 'identity'
      ? 'Captions describing the identity — remove identifying face / hair terms'
      : 'Captions leaking the training target — remove the terms identified in the warning above';
  const duplicateLabel = (image) => [
    image.filename ? `file ${image.filename}` : `image ${image.id}`,
    image.framing && `${image.framing} framing`,
    image.training_usefulness && `${image.training_usefulness} technical quality`,
    image.caption && `caption: ${image.caption}`,
  ].filter(Boolean).join(', ');
  const qualityLabel = (image) => [
    image.filename ? `file ${image.filename}` : `image ${image.id}`,
    `technical quality: ${image.technical || 'not checked'}`,
    `face-region quality: ${image.face_quality || 'not checked'}`,
  ].join(', ');
  const isRedQuality = (image) => image.technical === 'red' || image.face_quality === 'red';
  const redQualityImages = qualityImages.filter(isRedQuality);
  const advisoryQualityImages = qualityImages.filter((image) => !isRedQuality(image));
  const orderedQualityImages = [...redQualityImages, ...advisoryQualityImages];
  const [rejected, setRejected] = useState({});   // imageId -> pending|done
  const [previewImage, setPreviewImage] = useState(null);
  const [pendingActions, setPendingActions] = useState(0);
  const [actionError, setActionError] = useState('');
  const dialogRef = useRef(null);
  useFocusTrap(dialogRef, true);
  useBodyScrollLock(true);
  const imgUrl = (fn) => datasetImageUrl(datasetId, fn);

  // Escape cancels, like dismissing a native confirm.
  useEscapeToClose(() => onResolve(false), pendingActions === 0);

  const reject = async (id) => {
    setActionError('');
    setRejected((m) => ({ ...m, [id]: 'pending' }));
    setPendingActions((count) => count + 1);
    try {
      const saved = await ds.setStatus(id, 'reject');
      if (saved) setRejected((m) => ({ ...m, [id]: 'done' }));
      else {
        setRejected((m) => { const next = { ...m }; delete next[id]; return next; });
        setActionError(`Image ${id} could not be rejected. It remains in the training set.`);
      }
    } finally {
      setPendingActions((count) => Math.max(0, count - 1));
    }
  };

  const saveCaption = async (id, value, original) => {
    if (value === original) return;
    setActionError('');
    setPendingActions((count) => count + 1);
    try {
      const saved = await ds.setCaption(id, value);
      if (!saved) setActionError(`The caption for image ${id} was not saved.`);
    } finally {
      setPendingActions((count) => Math.max(0, count - 1));
    }
  };

  return (
    <div role="dialog" aria-modal="true" aria-label="Before training"
      className="fixed inset-0 z-[9990] bg-black/80 flex items-center justify-center p-3"
      onClick={(e) => {
        if (e.target === e.currentTarget && pendingActions === 0) onResolve(false);
      }}>
      <div ref={dialogRef}
        className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-xl border border-amber-400/40 bg-app p-4 flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <span className="text-amber-300 font-semibold"><span aria-hidden>⚠️</span> Before training</span>
          <button type="button" onClick={() => onResolve(false)} disabled={pendingActions > 0}
            className="ml-auto text-content-subtle hover:text-content" aria-label="Cancel">✕</button>
        </div>

        {actionError && <p role="alert" className="m-0 text-xs text-red-300">⚠ {actionError}</p>}

        {/* Summary — the aggregate message, kept verbatim. */}
        {warnings.length > 0 && (
          <ul className="m-0 pl-4 flex flex-col gap-1 text-content-muted text-[0.8125rem] list-disc">
            {warnings.map((w, i) => <li key={i}>{w}</li>)}
          </ul>
        )}

        {/* WHICH captions leak — edit in place (saves when you click away). */}
        {leaks.length > 0 && (
          <div className="rounded-lg border border-amber-400/30 bg-amber-500/5 p-2.5 flex flex-col gap-2">
            <span className="text-amber-300 text-[0.8125rem] font-semibold">
              {leakGuidance} ({leaks.length})
            </span>
            {leaks.map((li) => (
              <div key={li.id} className="flex gap-2 items-start">
                <img src={imgUrl(li.filename)} alt={`image ${li.id}`} loading="lazy"
                  className="w-14 h-14 rounded object-cover shrink-0 bg-black" />
                <textarea defaultValue={li.caption} rows={2}
                  aria-label={`Caption of image ${li.id}`}
                  onBlur={(e) => saveCaption(li.id, e.target.value, li.caption)}
                  className="flex-1 bg-app/60 border border-amber-400/30 rounded px-2 py-1 text-[0.6875rem] text-content resize-y" />
              </div>
            ))}
          </div>
        )}

        {/* WHICH images have red or incomplete pixel QA — inspect before deciding. */}
        {qualityImages.length > 0 && (
          <div className="rounded-lg border border-red-400/30 bg-red-500/5 p-2.5 flex flex-col gap-2">
            <span className="text-red-300 text-[0.8125rem] font-semibold">
              Pixel QA review ({qualityImages.length}): {redQualityImages.length} red ·{' '}
              {advisoryQualityImages.length} amber or incomplete
            </span>

            {previewImage && (
              <div className="rounded-lg border border-red-400/30 bg-black/50 p-2 flex flex-col gap-2"
                aria-label="Full-size QA preview">
                <div className="flex items-start gap-2">
                  <span className="text-xs text-content-muted">{qualityLabel(previewImage)}</span>
                  <button type="button" onClick={() => setPreviewImage(null)}
                    className="ml-auto text-content-subtle hover:text-content text-xs"
                    aria-label="Close full-size QA preview">✕</button>
                </div>
                <img src={imgUrl(previewImage.filename)} alt={qualityLabel(previewImage)}
                  className="w-full max-h-[55vh] object-contain bg-black rounded" />
              </div>
            )}

            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {orderedQualityImages.map((image) => {
                const state = rejected[image.id];
                return (
                  <div key={image.id}
                    className={`rounded border border-red-400/20 p-1.5 flex flex-col gap-1 ${state === 'done' ? 'opacity-60' : ''}`}>
                    <button type="button" onClick={() => setPreviewImage(image)}
                      aria-label={`Inspect ${qualityLabel(image)} at full size`}
                      className="rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-300">
                      <img src={imgUrl(image.filename)} alt={qualityLabel(image)} loading="lazy"
                        className={`w-full h-28 rounded object-contain bg-black ${state === 'done' ? 'grayscale' : ''}`} />
                    </button>
                    <span className="text-[0.625rem] text-content-muted break-all">{image.filename}</span>
                    <span className="text-[0.625rem] text-content-muted">
                      technical quality: {image.technical || 'not checked'}<br />
                      face-region quality: {image.face_quality || 'not checked'}
                    </span>
                    <button type="button" disabled={Boolean(state)} onClick={() => reject(image.id)}
                      aria-label={`Reject ${qualityLabel(image)} from training`}
                      className="px-2 py-0.5 rounded bg-red-500/15 border border-red-500/40 text-red-300 text-[0.625rem] disabled:opacity-40">
                      {state === 'pending' ? 'Saving…' : state === 'done' ? '✕ rejected' : 'Reject this photo'}
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* WHICH pairs are near-duplicate — reject one of each. */}
        {dups.length > 0 && (
          <div className="rounded-lg border border-amber-400/30 bg-amber-500/5 p-2.5 flex flex-col gap-2">
            <span className="text-amber-300 text-[0.8125rem] font-semibold">
              Near-duplicate pairs ({dups.length}) — reject one of each
            </span>
            {dups.map((p, i) => {
              const resolved = rejected[p.a.id] === 'done' || rejected[p.b.id] === 'done';
              const saving = rejected[p.a.id] === 'pending' || rejected[p.b.id] === 'pending';
              return (
                <div key={`${p.a.id}-${p.b.id}-${i}`} className={`flex items-center gap-3 ${resolved ? 'opacity-60' : ''}`}>
                  {[p.a, p.b].map((im) => (
                    <div key={im.id} className="flex flex-col items-center gap-1">
                      <img src={imgUrl(im.filename)} alt={duplicateLabel(im)} loading="lazy"
                        className={`w-20 h-20 rounded object-cover bg-black ${rejected[im.id] === 'done' ? 'ring-2 ring-red-500 grayscale' : ''}`} />
                      <button type="button" disabled={resolved || saving} onClick={() => reject(im.id)}
                        aria-label={`Reject ${duplicateLabel(im)} from this near-duplicate pair`}
                        className="px-2 py-0.5 rounded bg-red-500/15 border border-red-500/40 text-red-300 text-[0.625rem] disabled:opacity-40">
                        {rejected[im.id] === 'pending' ? 'Saving…'
                          : rejected[im.id] === 'done' ? '✕ rejected' : 'Reject this'}
                      </button>
                    </div>
                  ))}
                  {resolved && <span className="text-emerald-400 text-[0.6875rem]">✓ resolved</span>}
                </div>
              );
            })}
          </div>
        )}

        <div className="flex items-center gap-2 pt-1">
          <button type="button" onClick={() => onResolve(false)} disabled={pendingActions > 0}
            className="px-3 py-1.5 rounded-lg bg-surface text-content text-sm">Cancel</button>
          <button type="button" onClick={() => onResolve(true)} disabled={pendingActions > 0}
            className="ml-auto px-3 py-1.5 rounded-lg bg-gradient-primary text-white text-sm font-semibold disabled:opacity-40">
            {pendingActions > 0 ? 'Saving fixes…' : 'Start anyway'}
          </button>
        </div>
      </div>
    </div>
  );
}
