import { createPortal } from 'react-dom'
import TrainingFeedbackPanel from './TrainingFeedbackPanel'
import { fmtBytes } from './trainingPanelModel'

/** Result-family browser, checkpoint actions, and imported LoRA inventory. */
export default function TrainingCheckpointBrowserView(props) {
  const {
    bestEpoch, bestEpochBusy, checkpointBase, checkpointBaseLabel, checkpointBaseOptions, checkpointHost, confirm,
    checkpointLorasLabel, checkpointMatchesTraining, checkpointTrainType, checkpointTypeLabel, checkpoints, checkpointsOpen,
    ckLoaded, cloudCkpts, datasetState, diskUsage, ds, findBestEpoch,
    imported, loadCheckpoints, onCheckpointTypeChange, openTrainingFolder, postTrain, refreshStatus,
    removeImported, setCheckpointBase, setCheckpointsOpen, status, toast, toastTrainError, togglePanel,
    trainingFeedback, variant,
  } = props
  const content = (
    <details id="ds-training-checkpoints" open={Boolean(checkpointHost) || checkpointsOpen}
      className="rounded-lg border border-border bg-surface open:pb-2.5 scroll-mt-20">
      <summary data-workspace-focus
        onClick={checkpointHost
          ? (event) => event.preventDefault()
          : togglePanel('checkpoints', checkpointsOpen, setCheckpointsOpen)}
        className="cursor-pointer select-none px-3 py-2 text-sm text-content font-semibold">
        📦 Checkpoints &amp; trained LoRAs
        <span className="ml-2 font-normal text-content-subtle text-[0.6875rem]">
          {ckLoaded
            ? `${checkpoints.length} local checkpoint(s) · ${cloudCkpts.length} synced cloud · ${imported.length} in ComfyUI${diskUsage?.total_bytes ? ` · ${fmtBytes(diskUsage.total_bytes)} on disk` : ''}`
            : 'the files your training runs produce'}
        </span>
      </summary>
      <div className="px-3 pt-1 flex flex-col gap-2">
        <div className="flex items-center gap-2 rounded-lg border border-border bg-app px-3 py-2 flex-wrap">
          <span className="text-content-muted text-[0.625rem] uppercase">Browse results</span>
          <select value={checkpointTrainType} onChange={(event) => onCheckpointTypeChange(event.target.value)}
            aria-label="LoRA family to browse"
            className="px-2 py-1 rounded-lg border border-border bg-surface text-content text-[0.75rem]">
            <option value="zimage">Z-Image</option>
            <option value="sdxl">SDXL</option>
            <option value="krea">Krea 2</option>
            <option value="flux">FLUX.1</option>
            <option value="flux2klein">FLUX.2 Klein</option>
          </select>
          {checkpointBaseOptions.length > 0 ? (
            <select value={checkpointBase} onChange={(event) => setCheckpointBase(event.target.value)}
              aria-label="Training base to browse"
              className="min-w-0 max-w-full px-2 py-1 rounded-lg border border-border bg-surface text-content text-[0.75rem]">
              {checkpointBaseOptions.map((item) => (
                <option key={`${checkpointTrainType}-${item.value}`} value={item.value}>{item.label}</option>
              ))}
            </select>
          ) : (
            <span className="text-content text-xs">{checkpointBaseLabel}</span>
          )}
          <span className="ml-auto text-content-subtle text-[0.625rem]">
            Independent from the next Training configuration
          </span>
        </div>
        {/* Provenance du dataset : version courante + alerte si le dataset a
            changé depuis le dernier entraînement (les checkpoints listés ne
            reflètent alors PLUS l'état actuel). */}
        {datasetState?.registered && (datasetState.changed ? (
          <p className="m-0 rounded-md border border-amber-400/40 bg-amber-500/10 px-2 py-1 text-amber-200 text-[0.6875rem]">
            ⚠ The dataset has <b>changed since v{datasetState.version}</b>
            {datasetState.diff && (
              <>
                {' '}(
                {[
                  datasetState.diff.images_added ? `+${datasetState.diff.images_added} image${datasetState.diff.images_added > 1 ? 's' : ''}` : null,
                  datasetState.diff.images_removed ? `−${datasetState.diff.images_removed} image${datasetState.diff.images_removed > 1 ? 's' : ''}` : null,
                  datasetState.diff.captions_changed ? `${datasetState.diff.captions_changed} caption${datasetState.diff.captions_changed > 1 ? 's' : ''} edited` : null,
                  datasetState.diff.images_edited ? `${datasetState.diff.images_edited} image${datasetState.diff.images_edited > 1 ? 's' : ''} edited` : null,
                ].filter(Boolean).join(', ')}
                )
              </>
            )}
            {' '}— these checkpoints reflect the old state; the next training becomes <b>v{datasetState.version + 1}</b>.
          </p>
        ) : (
          <p className="m-0 text-content-subtle text-[0.625rem]">
            Dataset version: <span className="text-content font-semibold">v{datasetState.version}</span> — unchanged since the last training.
          </p>
        ))}
        <TrainingFeedbackPanel feedback={trainingFeedback} />
        <div className="flex items-center gap-2 flex-wrap">
          {/* () => … sinon React passe l'event en 1er arg → forBase = PointerEvent
              → base_model=[object Object] → run inexistant → liste vide. */}
          <button type="button" onClick={() => loadCheckpoints(checkpointBase, checkpointTrainType)}
            title="Reload the checkpoint list for this results filter"
            className="px-3 py-1.5 rounded-lg bg-surface-raised border border-border text-content text-xs font-semibold">
            ↻ Refresh checkpoints
          </button>
          {/* Ouvre les dossiers dans l'explorateur du poste (app locale) :
              loras = imports ComfyUI de la famille ; run = checkpoints bruts. */}
          <button type="button"
            onClick={() => openTrainingFolder(
              { target: 'loras', train_type: checkpointTrainType })}
            title={`Open the ComfyUI folder where imported ${checkpointTypeLabel} LoRAs live`}
            className="px-3 py-1.5 rounded-lg bg-surface-raised border border-border text-content text-xs font-semibold">
            📂 LoRA folder
          </button>
          <button type="button"
            onClick={() => openTrainingFolder(
              { target: 'run', train_type: checkpointTrainType, base_model: checkpointBase })}
            title="Open this run's output folder (raw checkpoints, samples, training log)"
            className="px-3 py-1.5 rounded-lg bg-surface-raised border border-border text-content text-xs font-semibold">
            📂 Run folder
          </button>
          <span className="text-content-subtle text-[0.625rem]">
            import the checkpoint you like into ComfyUI to use (and test) the LoRA
          </span>
        </div>

        {checkpoints.length > 0 && (
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-content-muted text-[0.625rem] uppercase">
                {checkpointTypeLabel} checkpoints — base « {checkpointBaseLabel} » (pick the earliest one that holds the identity)
              </span>
              <button type="button" disabled={bestEpochBusy}
                onClick={findBestEpoch}
                title="Scores every training sample vs the reference photo (face similarity, CPU) and recommends the checkpoint that holds the identity best — needs the Quality tools (ML extras)."
                className="px-2.5 py-1 rounded-lg bg-amber-500/15 border border-amber-400/40 text-amber-200 text-[0.6875rem] font-semibold disabled:opacity-40">
                {bestEpochBusy ? '🏆 Scoring samples…' : '🏆 Find best epoch'}
              </button>
              <button type="button" disabled={status.in_progress || !checkpointMatchesTraining}
                onClick={async () => {
                  const last = Math.max(...checkpoints.map((c) => c.step));
                  if (await confirm({
                    title: `Continue training from step ${last}?`,
                    message: `Resume “${checkpointBaseLabel}” for 1,000 more steps, targeting step ${last + 1000}.`,
                    confirmLabel: 'Continue training',
                    tone: 'warning',
                  })) {
                    await ds.continueTraining(1000, checkpointBase, variant, checkpointTrainType); refreshStatus(); loadCheckpoints(checkpointBase, checkpointTrainType);
                  }
                }}
                title={!checkpointMatchesTraining
                  ? 'To continue this run, select the same LoRA family and base in Training first'
                  : 'Resumes from this base’s last checkpoint and trains 1000 more steps'}
                className="ml-auto px-2.5 py-1 rounded-lg bg-indigo-500/20 border border-indigo-400/40 text-indigo-200 text-[0.6875rem] font-semibold disabled:opacity-40">
                ▶ Continue training (+1000)
              </button>
            </div>
            {bestEpoch && !bestEpoch.available && (
              <p className="m-0 text-amber-300 text-[0.625rem]">🏆 {bestEpoch.reason}</p>
            )}
            {bestEpoch?.available && (
              <p className="m-0 text-amber-200 text-[0.625rem]">
                🏆 Best identity at <span className="font-semibold">step {bestEpoch.best_step}</span>
                {' '}({(bestEpoch.steps.find((s) => s.step === bestEpoch.best_step)?.mean_sim ?? 0).toFixed(2)} mean similarity)
                {' '}— per step: {bestEpoch.steps.map((s) => `${s.step}:${s.mean_sim.toFixed(2)}`).join(' · ')}
              </p>
            )}
            {checkpoints.map((c) => (
              <div key={c.filename} className="flex items-center gap-2 text-[0.6875rem]">
                <span className={c.final ? 'text-green-400 font-semibold' : 'text-content'}>
                  {c.final ? '✓ final (training complete)' : `step ${c.step}`}
                </span>
                {c.version && (
                  <span className="px-1.5 py-px rounded border border-border bg-surface-raised text-content-subtle"
                    title={`Trained on dataset version v${c.version}${c.source ? ` (${c.source} run)` : ''}${datasetState?.changed ? ' — the dataset has changed since' : ''}`}>
                    v{c.version}{c.source === 'cloud' ? ' ☁' : ''}
                  </span>
                )}
                {bestEpoch?.available && bestEpoch.checkpoint === c.filename && (
                  <span className="px-1.5 py-px rounded border border-amber-400/50 bg-amber-400/15 text-amber-200 font-semibold"
                    title={`Closest checkpoint to the best-scoring step (${bestEpoch.best_step})`}>
                    🏆 recommended
                  </span>
                )}
                <button type="button"
                  onClick={async () => {
                    // await + refresh: the import must show up in "IN COMFYUI"
                    // without a manual Refresh click (user-observed). finally:
                    // the list refreshes even if the import failed (the error
                    // toast comes from the hook).
                    try { await ds.importCheckpoint(c.filename, checkpointBase, checkpointTrainType); }
                    finally { loadCheckpoints(checkpointBase, checkpointTrainType); }
                  }}
                  className="ml-auto px-2 py-0.5 rounded bg-primary/20 border border-primary/40 text-white">
                  Import → {checkpointLorasLabel}
                </button>
                <button type="button"
                  onClick={async () => {
                    if (!(await confirm({
                      title: `Move “${c.filename}” to trash?`,
                      message: 'The checkpoint can be restored until you empty the trash in Settings.',
                      confirmLabel: 'Move to trash',
                      tone: 'warning',
                    }))) return;
                    const d = await postTrain(`/api/dataset/${ds.currentId}/train/run-checkpoint/delete`,
                      { filename: c.filename, base_model: checkpointBase, train_type: checkpointTrainType });
                    if (d.ok === false) toastTrainError(d, 'Delete failed');
                    loadCheckpoints(checkpointBase, checkpointTrainType);
                  }}
                  title="Move this checkpoint to the trash (recoverable until the trash is emptied in Settings)"
                  className="px-2 py-0.5 rounded bg-red-500/15 border border-red-500/40 text-red-300">
                  🗑
                </button>
              </div>
            ))}
            <div className="flex items-center gap-2">
              <button type="button"
                onClick={async () => {
                  const finals = checkpoints.filter((c) => c.final).map((c) => c.filename);
                  const best = bestEpoch?.available ? [bestEpoch.checkpoint] : [];
                  const keep = [...new Set([...finals, ...best])];
                  if (!keep.length) {
                    // no final yet (unfinished run): keep the last step
                    const last = checkpoints[checkpoints.length - 1];
                    if (last) keep.push(last.filename);
                  }
                  const removed = checkpoints.filter((c) => !keep.includes(c.filename)).length;
                  if (!removed) return;
                  if (!(await confirm({
                    title: 'Clean up this training run?',
                    message: `Keep ${keep.length} checkpoint${keep.length === 1 ? '' : 's'} (${keep.join(', ')}) and move ${removed} other checkpoint${removed === 1 ? '' : 's'} to the trash. They remain recoverable until you empty the trash in Settings.`,
                    confirmLabel: 'Clean up run',
                    tone: 'warning',
                  }))) return;
                  const d = await postTrain(`/api/dataset/${ds.currentId}/train/checkpoints/cleanup`,
                    { keep_filenames: keep, base_model: checkpointBase, train_type: checkpointTrainType });
                  if (d.ok === false) toastTrainError(d, 'Cleanup failed');
                  loadCheckpoints(checkpointBase, checkpointTrainType);
                }}
                title="Keep the final (+ the 🏆 best-epoch pick if scored) and move every other checkpoint of this run to the trash"
                className="px-2.5 py-1 rounded-lg bg-red-500/10 border border-red-500/30 text-red-200 text-[0.6875rem] font-semibold">
                🧹 Clean up this run
              </button>
              <span className="text-content-subtle text-[0.625rem]">
                keeps final{bestEpoch?.available ? ' + 🏆 best' : ''} — the rest goes to the trash
              </span>
            </div>
          </div>
        )}

        {cloudCkpts.length > 0 && (
          <div className="flex flex-col gap-1">
            <span className="text-content-muted text-[0.625rem] uppercase">
              ☁ Cloud checkpoints (synced locally — every epoch harvested from the pod)
            </span>
            {cloudCkpts.map((c) => (
              <div key={`cr${c.run_id}-${c.filename}`} className="flex items-center gap-2 text-[0.6875rem]">
                <span className={c.final ? 'text-green-400 font-semibold' : 'text-content'}>
                  {c.final ? '✓ final (training complete)' : `step ${c.step}`}
                </span>
                <span className="px-1.5 py-px rounded border border-sky-500/40 bg-sky-500/10 text-sky-200"
                  title={`Cloud run #${c.run_id}${c.version ? ` · dataset v${c.version}` : ''}${c.trained_at ? ` · ${new Date(/[Z+]/.test(c.trained_at) ? c.trained_at : `${c.trained_at}Z`).toLocaleString()}` : ''}`}>
                  ☁{c.version ? ` v${c.version}` : ''}{c.active ? ' · run in progress' : ''}
                </span>
                <button type="button"
                  onClick={async () => {
                    const d = await postTrain(`/api/dataset/${ds.currentId}/train/import`,
                      { filename: c.filename, train_type: checkpointTrainType, cloud_run_id: c.run_id });
                    // Success must be VISIBLE: without the toast a working
                    // import looked like a dead button (user-observed).
                    if (d.ok === false) toastTrainError(d, 'Import failed');
                    else toast.success(`LoRA imported: ${d.dest || c.filename}`);
                    loadCheckpoints(checkpointBase, checkpointTrainType);
                  }}
                  title={c.active ? 'Import the latest synced save — the run keeps training' : 'Import this cloud checkpoint into ComfyUI'}
                  className="ml-auto px-2 py-0.5 rounded bg-primary/20 border border-primary/40 text-white">
                  Import → {checkpointLorasLabel}
                </button>
                {!c.active && (
                  <button type="button"
                    onClick={async () => {
                      if (!(await confirm({
                        title: `Move “${c.filename}” to trash?`,
                        message: 'The cloud checkpoint can be restored until you empty the trash in Settings.',
                        confirmLabel: 'Move to trash',
                        tone: 'warning',
                      }))) return;
                      const d = await postTrain(`/api/dataset/${ds.currentId}/train/run-checkpoint/delete`,
                        { filename: c.filename, cloud_run_id: c.run_id });
                      if (d.ok === false) toastTrainError(d, 'Delete failed');
                      loadCheckpoints(checkpointBase, checkpointTrainType);
                    }}
                    title="Move this cloud save to the trash"
                    className="px-2 py-0.5 rounded bg-red-500/15 border border-red-500/40 text-red-300">
                    🗑
                  </button>
                )}
              </div>
            ))}
          </div>
        )}

        {ckLoaded && checkpoints.length === 0 && cloudCkpts.length === 0 && !status.in_progress && (
          <p className="m-0 text-content-subtle text-[0.625rem]">
            No {checkpointTypeLabel} checkpoint for base « {checkpointBaseLabel} » — run a training on this base first.
          </p>
        )}

        {imported.length > 0 && (
          <div className="flex flex-col gap-1">
            <span className="text-content-muted text-[0.625rem] uppercase">
              In ComfyUI ({checkpointLorasLabel}) — delete the ones you no longer need
            </span>
            {imported.map((c) => (
              <div key={c.filename} className="flex items-center gap-2 text-[0.6875rem]">
                <span className="text-content break-all">{c.label}</span>
                {/* Retrofit signal: the file's REAL arch (read from its header)
                    contradicts this folder's family — a mislabelled deploy that
                    would test as a silent no-op. No auto-move; just flag it. */}
                {c.arch_mismatch && (
                  <span
                    title={`This file is a ${c.arch_label || c.arch_mismatch} LoRA, not ${checkpointLorasLabel} — testing it here has NO effect (ComfyUI silently drops it). Delete it and re-import under the ${c.arch_label || c.arch_mismatch} family.`}
                    className="px-1.5 py-0.5 rounded bg-amber-500/15 border border-amber-500/40 text-amber-300 whitespace-nowrap">
                    ⚠ {c.arch_label || c.arch_mismatch} LoRA
                  </span>
                )}
                <button type="button" onClick={() => removeImported(c.filename, c.label)}
                  title={`Move this LoRA from ComfyUI's ${checkpointLorasLabel} folder to Trash`}
                  className="ml-auto px-2 py-0.5 rounded bg-red-500/15 border border-red-500/40 text-red-300">
                  🗑 Trash
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </details>
  )
  return props.checkpointHost ? createPortal(content, props.checkpointHost) : content
}
