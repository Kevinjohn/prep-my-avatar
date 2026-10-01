import { squareCrop } from './hostedExportModel';

const FIELD = 'w-full rounded border border-border bg-surface px-2 py-1.5 text-sm text-content';
const BUTTON = 'rounded border border-border bg-surface px-3 py-1.5 text-sm text-content disabled:opacity-40';

export default function HostedExportSelection({ image, entry, onChange, onPreview, onApprove, busy, cropRule }) {
  const training = entry.role === 'training' && cropRule === 'square';
  const title = `${entry.role[0].toUpperCase()}${entry.role.slice(1)}`;
  const width = image.width;
  const height = image.height;
  const side = Math.min(width, height);
  const crop = entry.crop || [(width - side) / (2 * width), (height - side) / (2 * height), (width + side) / (2 * width), (height + side) / (2 * height)];
  const box = entry.crop_box || { left: Math.round(crop[0] * width), top: Math.round(crop[1] * height), side: Math.round((crop[2] - crop[0]) * width) };
  const validCrop = !training || Boolean(squareCrop(image, box));
  const setCrop = (field, value) => {
    const crop_box = { ...box, [field]: value === '' ? '' : Number(value) };
    onChange({ crop_box, crop: squareCrop(image, crop_box) });
  };
  return <fieldset className="min-w-0 rounded-lg border border-border p-3 flex flex-col gap-3">
    <legend className="px-1 text-sm font-semibold text-content">{title} photo {image.id}</legend>
    {entry.role === 'reference' && <div className="grid gap-2 sm:grid-cols-2">
      <label className="text-sm text-content-muted">Reference purpose for photo {image.id}
        <input className={FIELD} value={entry.reference_role || ''} onChange={(event) => onChange({ reference_role: event.target.value })} placeholder="Face identity, body proportions, setting…" /></label>
      <label className="text-sm text-content-muted">Reference order for photo {image.id}
        <input className={FIELD} type="number" min="1" step="1" value={entry.reference_order || 1} onChange={(event) => onChange({ reference_order: Number(event.target.value) })} /></label>
    </div>}
    {training && <>
      <p className="m-0 text-sm text-content-muted">Square crop only. Check whether it removes the face, hands or body; adjust the crop or exclude this photo. No padding or stretching.</p>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        {['left', 'top', 'side'].map((field) => <label key={field} className="text-sm text-content-muted">{title} crop {field} for photo {image.id}
          <input className={FIELD} type="number" min={field === 'side' ? 1 : 0} max={field === 'left' ? width - box.side : field === 'top' ? height - box.side : Math.min(width - box.left, height - box.top)} step="1" value={box[field]} onChange={(event) => setCrop(field, event.target.value)} /></label>)}
      </div>
      {!validCrop && <p role="alert" className="m-0 text-sm text-content">Enter a positive square side and coordinates inside the source image.</p>}
      <span className="text-xs text-content-subtle">Source {width} × {height} pixels. Crop controls use source pixels.</span>
    </>}
    <label className="text-sm text-content-muted">{title} caption override for photo {image.id}
      <textarea className={FIELD} rows={3} value={entry.caption_override ?? ''} onChange={(event) => onChange({ caption_override: event.target.value })} placeholder={image.caption || 'Use the master caption with trigger fallback'} />
    </label>
    <button type="button" className={`${BUTTON} self-start`} onClick={() => onChange({ caption_override: null })}>Use master caption for {entry.role} photo {image.id}</button>
    <p className="m-0 text-xs text-content-subtle">Master caption: {image.caption || '(empty — trigger fallback)'}. Target overrides leave the master caption unchanged.</p>
    <button type="button" className={`${BUTTON} self-start`} disabled={busy || !validCrop} onClick={onPreview}>Preview {entry.role} photo {image.id}</button>
    {entry.preview && <div className="flex flex-col gap-2">
      <img src={entry.preview.image_data_url} alt={`Exact ${entry.role} export for photo ${image.id}`} className="max-h-80 max-w-full self-start object-contain rounded border border-border" />
      <p className="m-0 whitespace-pre-wrap break-words text-sm text-content">Final caption: {entry.preview.caption}</p>
      {entry.preview.warnings?.map((warning, index) => <p key={index} className="m-0 text-sm text-content-muted">Warning: {warning}</p>)}
      <details className="text-xs text-content-subtle"><summary>Exact artifact hashes</summary><p className="break-all">Image: {entry.preview.image_sha256}<br />Caption: {entry.preview.caption_sha256}<br />Source and transform: {entry.preview.pair_sha256}</p></details>
      <label className="flex items-start gap-2 text-sm text-content"><input type="checkbox" checked={Boolean(entry.approval)} onChange={(event) => onApprove(event.target.checked)} />
        Approve exact {entry.role} image and caption for photo {image.id}</label>
    </div>}
  </fieldset>;
}
