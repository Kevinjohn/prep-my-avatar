import { useEffect, useRef, useState } from 'react';
import { apiFetch, postJson, fetchWithCsrfRetry, getCsrfToken } from '../../api/fetchClient';
import HostedExportSettings from './HostedExportSettings';
import HostedExportSelection from './HostedExportSelection';
import { createHostedDraft, updateHostedSelection, reviewKey, hostedExportErrors, hostedExportPayload } from './hostedExportModel';

const BUTTON = 'rounded border border-border bg-surface px-3 py-1.5 text-sm text-content disabled:opacity-40';
const withoutReviews = (entry) => {
  const { approval: _approval, preview: _preview, ...rest } = entry;
  return rest;
};

export default function HostedExportPanel({ datasetId }) {
  const [open, setOpen] = useState(false);
  const [snapshot, setSnapshot] = useState(null);
  const [draft, setDraft] = useState(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState('');
  const latest = useRef(null);
  const operation = useRef(0);
  const activeRequest = useRef(0);
  const base = `/api/dataset/${datasetId}/hosted-export`;
  const storageKey = `hosted-export-draft-v1:${datasetId}`;
  const replace = (next) => { latest.current = next; setDraft(next); };

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    activeRequest.current += 1;
    setBusy('Loading');
    apiFetch(base).then((data) => {
      if (cancelled) return;
      const fresh = createHostedDraft(data);
      let restored = null;
      try { restored = JSON.parse(localStorage.getItem(storageKey) || 'null'); } catch {}
      const usable = restored && Array.isArray(restored.selections) && restored.subject && restored.parameters
        && data.recipes.some((recipe) => recipe.id === restored.recipe_id && recipe.version === restored.recipe_version);
      const next = usable ? { ...restored, dataset_revision: data.dataset_revision, selections: restored.selections.filter((entry) => data.images.some((image) => image.id === entry.image_id)).map(withoutReviews) } : fresh;
      setSnapshot(data); latest.current = next; setDraft(next);
      if (usable) setNotice(restored.dataset_revision === data.dataset_revision ? 'Local draft restored. Preview and approve each selected pair again.' : 'Dataset changed since this draft. Selections restored; review the current sources again.');
      setError('');
    }).catch((failure) => { if (!cancelled) setError(failure.message); })
      .finally(() => { if (!cancelled) setBusy(''); });
    return () => { cancelled = true; operation.current += 1; activeRequest.current += 1; };
  }, [open, base, storageKey]);

  useEffect(() => {
    if (!draft) return;
    try {
      localStorage.setItem(storageKey, JSON.stringify({ ...draft, selections: draft.selections.map(withoutReviews) }));
    } catch { setNotice('This browser could not save the draft. Keep this page open until you download the package.'); }
  }, [draft, storageKey]);

  const changeSettings = (patch) => {
    operation.current += 1;
    replace({ ...latest.current, ...patch, selections: latest.current.selections.map((entry) => {
      const clean = withoutReviews(entry);
      if (patch.recipe_id) { delete clean.crop_box; clean.crop = null; }
      return clean;
    }) });
  };
  const changeEntry = (index, patch) => {
    operation.current += 1;
    replace(updateHostedSelection(latest.current, index, patch));
  };
  const toggleRole = (image, role, enabled) => {
    operation.current += 1;
    const current = latest.current;
    let selections = current.selections.filter((entry) => !(entry.image_id === image.id && entry.role === role));
    if (enabled) {
      selections = selections.filter((entry) => entry.image_id !== image.id || (role === 'evaluation' ? false : entry.role !== 'evaluation'));
      selections.push({ image_id: image.id, role, crop: null, caption_override: null,
        burst_group: image.duplicate_group ? String(image.duplicate_group) : '',
        ...(role === 'reference' ? { reference_role: '', reference_order: Math.max(0, ...selections.filter((entry) => entry.role === 'reference').map((entry) => entry.reference_order || 0)) + 1 } : {}) });
    }
    replace({ ...current, selections });
  };
  const preview = async (index) => {
    const current = latest.current;
    const entry = current.selections[index];
    const key = reviewKey(current, entry);
    const requestId = ++operation.current;
    const lifecycleId = ++activeRequest.current;
    setError(''); setBusy(`Previewing ${entry.role} photo ${entry.image_id}`);
    try {
      const result = await postJson(`${base}/preview`, { recipe_id: current.recipe_id,
        recipe_version: current.recipe_version, parameters: current.parameters, image_id: entry.image_id,
        role: entry.role, crop: entry.crop, caption_override: entry.caption_override, trigger_word: current.subject.trigger_word });
      const present = latest.current.selections[index];
      if (operation.current !== requestId || !present || reviewKey(latest.current, present) !== key) return;
      replace(updateHostedSelection(latest.current, index, { preview: { ...result, key } }));
    } catch (failure) { if (activeRequest.current === lifecycleId && operation.current === requestId) setError(failure.message); }
    finally { if (activeRequest.current === lifecycleId) setBusy(''); }
  };
  const approve = (index, approved) => {
    const current = latest.current;
    const entry = current.selections[index];
    if (approved && entry.preview?.key !== reviewKey(current, entry)) return;
    replace({ ...current, selections: current.selections.map((item, i) => i === index ? { ...item, approval: approved ? { key: entry.preview.key,
      image_sha256: entry.preview.image_sha256, caption_sha256: entry.preview.caption_sha256, pair_sha256: entry.preview.pair_sha256 } : undefined } : item) });
  };
  const download = async () => {
    if (busy || hostedExportErrors(latest.current, snapshot).length) return;
    const lifecycleId = ++activeRequest.current;
    setBusy('Building package'); setError('');
    try {
      const response = await fetchWithCsrfRetry(base, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() }, body: JSON.stringify(hostedExportPayload(latest.current, snapshot)) });
      if (!response.ok) {
        let message = `Export failed (HTTP ${response.status}).`;
        try { message = (await response.json()).error || message; } catch {}
        throw new Error(message);
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a'); link.href = url; link.download = 'reviewed_hosted_export.zip';
      document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      if (activeRequest.current === lifecycleId) setNotice('Reviewed hosted package downloaded. Keep it private until you choose where to upload it.');
    } catch (failure) { if (activeRequest.current === lifecycleId) setError(failure.message); }
    finally { if (activeRequest.current === lifecycleId) setBusy(''); }
  };
  const recipe = draft && snapshot?.recipes.find((item) => item.id === draft.recipe_id && item.version === draft.recipe_version);
  const errors = draft && snapshot ? hostedExportErrors(draft, snapshot) : [];
  return <section id="ds-export-hosted" aria-label="Hosted person export" className="rounded-lg border border-border bg-surface px-3 py-3 flex flex-col gap-3">
    <h2 className="m-0 text-base font-semibold text-content">Hosted person export</h2>
    <p className="m-0 text-sm text-content-muted">Prepare reviewed training pairs, ordered references and separate evaluation photos for a manual hosted workflow. Originals and master captions stay in your corpus.</p>
    <button type="button" className={`${BUTTON} self-start`} aria-expanded={open} onClick={() => setOpen(!open)}>{open ? 'Close hosted draft' : 'Prepare hosted export'}</button>
    {open && <>
      {busy && <p role="status" className="m-0 text-sm text-content-muted">{busy}…</p>}
      {error && <div role="alert" className="text-sm text-content"><p className="m-0">{error}</p><button type="button" className={BUTTON} disabled={Boolean(busy)} onClick={() => { setOpen(false); setTimeout(() => setOpen(true), 0); }}>Reload current dataset</button></div>}
      {notice && <p role="status" className="m-0 text-sm text-content-muted">{notice}</p>}
      {draft && snapshot && <>
        <HostedExportSettings draft={draft} recipes={snapshot.recipes} onChange={changeSettings} />
        <p className="m-0 text-sm text-content-muted">{recipe?.count_guidance && <>Planning guidance: {Object.entries(recipe.count_guidance).map(([role, count]) => `${count} ${role}`).join(', ')} photos. </>}Minimum training photos: {recipe?.input_requirements?.minimum_training_images}. Evaluation must use separate source families and burst groups.</p>
        {snapshot.images.length === 0 && <p role="status">No photos are available. Import and review photos first.</p>}
        {snapshot.images.map((image) => {
          const entries = draft.selections.map((entry, index) => ({ entry, index })).filter(({ entry }) => entry.image_id === image.id);
          return <article key={image.id} className="min-w-0 rounded-lg border border-border p-3 flex flex-col gap-3">
            <h3 className="m-0 text-sm font-semibold text-content">Photo {image.id} · {image.framing || 'framing unknown'}</h3>
            <div className="flex flex-wrap gap-3 text-sm text-content">
              {['training', 'reference', 'evaluation'].map((role) => <label key={role} className="flex gap-2 items-center"><input type="checkbox" aria-label={`Photo ${image.id} ${role}`} disabled={!image.eligible || Boolean(image.role_exclusions?.[role]) || (role === 'reference' && image.anchor_decision === 'excluded')} checked={entries.some(({ entry }) => entry.role === role)} onChange={(event) => toggleRole(image, role, event.target.checked)} />{role}</label>)}
              <span>{entries.length ? `${entries.length} selected roles` : 'Excluded from this package'}</span>
            </div>
            {!image.eligible && <p className="m-0 text-sm text-content-muted">Excluded: {image.exclusion_reason || 'Admission or rights rules'}</p>}
            {image.role_exclusions?.evaluation && <p className="m-0 text-sm text-content-muted">Evaluation unavailable: {image.role_exclusions.evaluation}</p>}
            {image.anchor_decision === 'excluded' && <p className="m-0 text-sm text-content-muted">Provider reference exclusion is retained.</p>}
            {entries.length > 0 && <>
              <img src={image.source_preview_url} alt={`Selected source for photo ${image.id}`} className="max-h-48 max-w-full self-start object-contain rounded border border-border" />
              <label className="text-sm text-content-muted">Burst group for photo {image.id}<input className="w-full rounded border border-border bg-surface px-2 py-1.5 text-sm text-content" value={entries[0].entry.burst_group || ''} onChange={(event) => {
                operation.current += 1;
                replace({ ...latest.current, selections: latest.current.selections.map((entry) => entry.image_id === image.id ? { ...withoutReviews(entry), burst_group: event.target.value } : entry) });
              }} placeholder="Group photos from the same capture burst" /></label>
              {entries.map(({ entry, index }) => <HostedExportSelection key={entry.role} image={image} entry={entry} onChange={(patch) => changeEntry(index, patch)} onPreview={() => preview(index)} onApprove={(approved) => approve(index, approved)} busy={Boolean(busy)} cropRule={recipe?.crop_rule} />)}
            </>}
          </article>;
        })}
        {errors.length > 0 && <div className="text-sm text-content-muted"><p className="m-0">Before download:</p><ul className="list-disc pl-5">{errors.map((message) => <li key={message}>{message}</li>)}</ul></div>}
        <button type="button" className="self-start rounded-lg bg-gradient-primary px-4 py-2 text-sm font-semibold text-white disabled:opacity-40" disabled={Boolean(busy) || errors.length > 0} onClick={download}>Download reviewed hosted package</button>
      </>}
    </>}
  </section>;
}
