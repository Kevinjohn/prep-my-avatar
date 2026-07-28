import { useRef } from 'react'
import { useBodyScrollLock } from '../../hooks/useBodyScrollLock'
import { useFocusTrap } from '../../hooks/useFocusTrap'

export default function ResumeTrainingDialog({ checkpoint, onResolve }) {
  const dialogRef = useRef(null)
  useFocusTrap(dialogRef, true)
  useBodyScrollLock(true)

  return (
    <div role="dialog" aria-modal="true" aria-label="Previous training run found"
      className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4"
      onKeyDown={(event) => { if (event.key === 'Escape') onResolve(null) }}>
      <div ref={dialogRef}
        className="w-full max-w-md rounded-xl border border-border bg-surface-overlay p-4 flex flex-col gap-3">
        <h3 className="m-0 text-content font-bold text-sm">
          ⚠ Previous run found ({checkpoint.final ? 'complete' : 'stopped'} · step {checkpoint.latest})
        </h3>
        <p className="m-0 text-content-muted text-[0.8125rem] leading-relaxed">
          Training will <b className="text-content">resume that LoRA</b> from its last
          checkpoint — anything it learned from images you have since removed stays in
          its weights. If the dataset changed, start fresh instead: the old run is
          archived (not deleted) and checkpoints already imported into ComfyUI are kept.
        </p>
        <div className="flex items-center gap-2 flex-wrap">
          <button type="button" onClick={() => onResolve('fresh')}
            className="px-3 py-1.5 rounded-lg bg-gradient-primary text-white text-sm font-semibold">
            ↺ Start fresh
          </button>
          <button type="button" onClick={() => onResolve('resume')}
            title="Continue the existing LoRA from its last checkpoint (only useful with a HIGHER step target)."
            className="px-3 py-1.5 rounded-lg border border-border bg-surface text-content text-sm hover:bg-surface-raised">
            ▶ Continue from step {checkpoint.latest}
          </button>
          <button type="button" onClick={() => onResolve(null)}
            className="ml-auto px-3 py-1.5 rounded-lg text-content-muted hover:text-content text-sm">
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}
