import { useRef, useState } from 'react';
import { datasetImageUrl } from './datasetImageUrl';

// Must match MAX_EXTRA_REFS in face_dataset_service.
const MAX_EXTRA_REFS = 3;

function roleLabel(item, supportingIndex) {
  if (item.role === 'primary_reference') return 'Primary — authoritative identity';
  return `Supporting reference ${supportingIndex}`;
}

export default function ReferencePanel({ refFilename, datasetId, onSetRef, onCropRef, busy, nonce = 0,
                                         extraRefs = [], onAddExtraRef, onRemoveExtraRef,
                                         onAnchorDecision, anchorPlan = null }) {
  const primaryInput = useRef(null);
  const extraInput = useRef(null);
  const [autoCrop, setAutoCrop] = useState(false);
  const [excludingId, setExcludingId] = useState(null);
  const imgUrl = (filename) => datasetImageUrl(datasetId, filename, nonce);
  const fallbackItems = [
    ...(refFilename ? [{ role: 'primary_reference', filename: refFilename, warnings: [] }] : []),
    ...extraRefs.map((filename) => ({
      role: 'additional_reference', filename, warnings: [],
    })),
  ];
  const items = anchorPlan ? (anchorPlan.items || []) : fallbackItems;
  let supportingIndex = 0;

  return (
    <section aria-labelledby="identity-pack-title" className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2 flex-wrap">
          <h2 id="identity-pack-title" className="m-0 text-lg font-semibold text-content">
            Identity reference pack
          </h2>
          <span className="rounded-full border border-border px-2 py-0.5 text-xs text-content-muted">
            {items.length}/{anchorPlan?.limit || 5} unique photos
          </span>
          {!!anchorPlan?.duplicates_removed && (
            <span className="rounded-full border border-warning/40 bg-warning/10 px-2 py-0.5 text-xs text-warning">
              {anchorPlan.duplicates_removed} exact {anchorPlan.duplicates_removed === 1 ? 'duplicate' : 'duplicates'} omitted
            </span>
          )}
        </div>
        <p className="m-0 max-w-4xl text-sm text-content-muted">
          Remote generation providers receive these unique photos in this order. Local Klein uses
          the primary plus hand-picked supporting photos; face scoring uses only the primary.
        </p>
      </div>

      <div role="note" className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-content">
        <span className="font-medium">More references are not automatically better.</span>{' '}
        Keep only clear, current photos of the same appearance. Sunglasses, hats, heavy shadows,
        old hairstyles, and conflicting facial hair can pull the result away from you.
      </div>

      {items.length > 0 ? (
        <ol aria-label="Ordered identity references" className="m-0 grid list-none gap-3 p-0 sm:grid-cols-2 xl:grid-cols-3">
          {items.map((item) => {
            if (item.role !== 'primary_reference') supportingIndex += 1;
            const label = roleLabel(item, supportingIndex);
            const canRemove = item.role === 'additional_reference' && extraRefs.includes(item.filename);
            return (
              <li key={`${item.role}-${item.image_id ?? item.filename}`}
                className="flex min-w-0 gap-3 rounded-lg border border-border bg-surface p-3">
                <div className="h-28 w-24 shrink-0 overflow-hidden rounded-lg bg-black">
                  <img src={imgUrl(item.filename)} alt={`${label} preview`}
                    className="h-full w-full object-cover" />
                </div>
                <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                  <span className={`text-sm font-medium ${item.role === 'primary_reference' ? 'text-accent' : 'text-content'}`}>
                    {label}
                  </span>
                  {item.role === 'primary_reference' && (
                    <span className="text-xs text-content-muted">Local + remote generation · face scoring</span>
                  )}
                  {item.role === 'additional_reference' && (
                    <span className="text-xs text-content-muted">Local + remote generation</span>
                  )}
                  {item.role === 'import' && (
                    <>
                      <span className="text-xs text-content-muted">
                        Remote generation only · automatically selected from reviewed photos
                      </span>
                      <button type="button"
                        aria-label={`Exclude ${label} from generation references`}
                        disabled={busy || excludingId === item.image_id}
                        onClick={async () => {
                          setExcludingId(item.image_id);
                          try {
                            await onAnchorDecision?.(item.image_id, 'excluded');
                          } finally {
                            setExcludingId(null);
                          }
                        }}
                        className="mt-auto self-start rounded-lg bg-surface-raised px-2.5 py-1 text-xs text-content disabled:opacity-40">
                        {excludingId === item.image_id ? 'Excluding…' : 'Exclude from generation'}
                      </button>
                      <span className="text-[0.625rem] text-content-subtle">Keeps this photo in the training set</span>
                    </>
                  )}
                  {item.warnings?.map((warning) => (
                    <span key={warning} className="text-xs text-warning">⚠ {warning}</span>
                  ))}
                  {item.role === 'primary_reference' && (
                    <div className="mt-auto flex flex-wrap items-center gap-1.5">
                      <button type="button" onClick={() => primaryInput.current?.click()} disabled={busy}
                        className="rounded-lg bg-surface-raised px-2.5 py-1 text-xs text-content disabled:opacity-40">
                        Change primary
                      </button>
                      <button type="button" onClick={onCropRef} disabled={busy}
                        className="rounded-lg bg-surface-raised px-2.5 py-1 text-xs text-content disabled:opacity-40">
                        Crop
                      </button>
                    </div>
                  )}
                  {canRemove && (
                    <button type="button" onClick={() => onRemoveExtraRef?.(item.filename)} disabled={busy}
                      className="mt-auto self-start rounded-lg bg-surface-raised px-2.5 py-1 text-xs text-content disabled:opacity-40">
                      Remove supporting photo
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      ) : (
        <div className="rounded-lg border border-dashed border-border-strong px-4 py-6 text-center">
          <p className="m-0 text-sm text-content-muted">
            No identity reference is selected. Add a clear, current, unobstructed face photo first.
          </p>
          <button type="button" onClick={() => primaryInput.current?.click()} disabled={busy}
            className="mt-3 rounded-lg bg-accent px-3 py-1.5 text-sm text-white disabled:opacity-40">
            Set primary reference
          </button>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
        {refFilename && extraRefs.length < MAX_EXTRA_REFS && (
          <button type="button" onClick={() => extraInput.current?.click()} disabled={busy}
            className="rounded-lg border border-border-strong bg-surface px-3 py-1.5 text-sm text-content disabled:opacity-40">
            Add supporting photo
          </button>
        )}
        <label className="flex items-center gap-1.5 text-xs text-content-muted cursor-pointer"
          title="A local vision pass finds the head and crops around it. This is slower and pauses ComfyUI.">
          <input type="checkbox" checked={autoCrop} onChange={(event) => setAutoCrop(event.target.checked)}
            className="h-3.5 w-3.5 accent-indigo-500" />
          Auto head-crop next primary upload
        </label>
        {items.some((item) => item.role === 'import') && (
          <a href={`#/datasets/${datasetId}/anchors`}
            className="text-xs text-accent underline underline-offset-2">
            Change automatic choices in Step 3
          </a>
        )}
      </div>

      <input ref={primaryInput} type="file" accept="image/*" className="hidden"
        aria-label="Upload primary identity reference"
        onChange={(event) => {
          if (event.target.files[0]) onSetRef(event.target.files[0], { autoCrop });
          event.target.value = '';
        }} />
      <input ref={extraInput} type="file" accept="image/*" className="hidden"
        aria-label="Upload supporting identity reference"
        onChange={(event) => {
          if (event.target.files[0]) onAddExtraRef?.(event.target.files[0]);
          event.target.value = '';
        }} />
    </section>
  );
}
