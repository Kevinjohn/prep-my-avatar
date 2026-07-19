import {
  createContext, useCallback, useContext, useEffect, useRef, useState,
} from 'react';
import { createPortal } from 'react-dom';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import { useBodyScrollLock } from '../../hooks/useBodyScrollLock';

const ConfirmDialogContext = createContext(null);

function PromptDialog({ request, onResolve }) {
  const dialogRef = useRef(null);
  const [value, setValue] = useState(request.defaultValue ?? '');
  useFocusTrap(dialogRef, true);
  useBodyScrollLock(true);
  const titleId = 'global-prompt-title';
  const descriptionId = request.message ? 'global-prompt-description' : undefined;
  const inputId = 'global-prompt-input';
  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.key === 'Escape') { event.preventDefault(); onResolve(null); }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [onResolve]);
  return createPortal(
    <div className="fixed inset-0 z-[10000] flex items-center justify-center bg-black/75 p-4"
      onMouseDown={(event) => { if (event.target === event.currentTarget) onResolve(null); }}>
      <section ref={dialogRef} role="dialog" aria-modal="true"
        aria-labelledby={titleId} aria-describedby={descriptionId}
        className="w-full max-w-md rounded-xl border border-border bg-app p-4 shadow-2xl">
        <h2 id={titleId} className="m-0 text-base font-semibold text-content">
          {request.title || 'Enter a value'}
        </h2>
        {request.message && (
          <p id={descriptionId} className="mb-0 mt-2 whitespace-pre-line text-sm leading-5 text-content-muted">
            {request.message}
          </p>
        )}
        <form className="mt-4" onSubmit={(event) => { event.preventDefault(); onResolve(value); }}>
          <label htmlFor={inputId} className="block text-xs font-medium text-content-muted">
            {request.inputLabel || 'Value'}
          </label>
          <input id={inputId} type={request.inputType || 'text'} value={value}
            min={request.min} step={request.step} placeholder={request.placeholder}
            onChange={(event) => setValue(event.target.value)}
            className="mt-1 w-full rounded-lg border border-border-strong bg-surface px-3 py-2 text-sm text-content focus:border-primary focus:outline-none" />
          <div className="mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <button type="button" onClick={() => onResolve(null)}
              className="rounded-lg border border-border bg-surface px-3 py-2 text-sm font-medium text-content-muted hover:text-content">
              {request.cancelLabel || 'Cancel'}
            </button>
            <button type="submit"
              className="rounded-lg bg-gradient-primary px-3 py-2 text-sm font-semibold text-white">
              {request.confirmLabel || 'Continue'}
            </button>
          </div>
        </form>
      </section>
    </div>,
    document.body,
  );
}

function ConfirmDialog({ request, onResolve }) {
  const dialogRef = useRef(null);
  useFocusTrap(dialogRef, true);
  useBodyScrollLock(true);
  const titleId = 'global-confirm-title';
  const descriptionId = 'global-confirm-description';
  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.key === 'Escape') { event.preventDefault(); onResolve(false); }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [onResolve]);
  const danger = request.tone === 'danger';
  return createPortal(
    <div className="fixed inset-0 z-[10000] flex items-center justify-center bg-black/75 p-4"
      onMouseDown={(event) => { if (event.target === event.currentTarget) onResolve(false); }}>
      <section ref={dialogRef} role="alertdialog" aria-modal="true"
        aria-labelledby={titleId} aria-describedby={descriptionId}
        className="w-full max-w-md rounded-xl border border-border bg-app p-4 shadow-2xl">
        <div className="flex items-start gap-3">
          <span aria-hidden className={danger ? 'text-red-300' : 'text-amber-300'}>
            {danger ? '⚠' : '!' }
          </span>
          <div className="min-w-0 flex-1">
            <h2 id={titleId} className="m-0 text-base font-semibold text-content">
              {request.title || 'Confirm action'}
            </h2>
            <p id={descriptionId}
              className="mb-0 mt-2 whitespace-pre-line text-sm leading-5 text-content-muted">
              {request.message}
            </p>
          </div>
        </div>
        <div className="mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          {/* Cancel is intentionally first in DOM/focus order for destructive actions. */}
          <button type="button" onClick={() => onResolve(false)}
            className="rounded-lg border border-border bg-surface px-3 py-2 text-sm font-medium text-content-muted hover:text-content">
            {request.cancelLabel || 'Cancel'}
          </button>
          <button type="button" onClick={() => onResolve(true)}
            className={`rounded-lg px-3 py-2 text-sm font-semibold text-white ${danger
              ? 'border border-red-400/40 bg-red-600 hover:bg-red-500'
              : 'bg-gradient-primary'}`}>
            {request.confirmLabel || 'Confirm'}
          </button>
        </div>
      </section>
    </div>,
    document.body,
  );
}

export function ConfirmDialogProvider({ children }) {
  const [active, setActive] = useState(null);
  const activeRef = useRef(null);
  const queueRef = useRef([]);
  const requestSequenceRef = useRef(0);

  const activate = useCallback((entry) => {
    activeRef.current = entry;
    setActive(entry);
  }, []);

  const confirm = useCallback((options) => new Promise((resolve) => {
    const entry = {
      kind: 'confirm', ...(typeof options === 'string' ? { message: options } : options), resolve,
      id: ++requestSequenceRef.current,
    };
    if (activeRef.current) queueRef.current.push(entry);
    else activate(entry);
  }), [activate]);

  const prompt = useCallback((options) => new Promise((resolve) => {
    const entry = {
      kind: 'prompt', ...(typeof options === 'string' ? { title: options } : options), resolve,
      id: ++requestSequenceRef.current,
    };
    if (activeRef.current) queueRef.current.push(entry);
    else activate(entry);
  }), [activate]);

  const resolveActive = useCallback((value) => {
    const current = activeRef.current;
    if (!current) return;
    current.resolve(current.kind === 'prompt' ? value : Boolean(value));
    const next = queueRef.current.shift() || null;
    activeRef.current = next;
    setActive(next);
  }, []);

  useEffect(() => () => {
    if (activeRef.current) activeRef.current.resolve(activeRef.current.kind === 'prompt' ? null : false);
    queueRef.current.forEach((entry) => entry.resolve(entry.kind === 'prompt' ? null : false));
    queueRef.current = [];
  }, []);

  return (
    <ConfirmDialogContext.Provider value={{ confirm, prompt }}>
      {children}
      {active?.kind === 'confirm' && (
        <ConfirmDialog key={active.id} request={active} onResolve={resolveActive} />
      )}
      {active?.kind === 'prompt' && (
        <PromptDialog key={active.id} request={active} onResolve={resolveActive} />
      )}
    </ConfirmDialogContext.Provider>
  );
}

export function useConfirmDialog() {
  const value = useContext(ConfirmDialogContext);
  if (!value) throw new Error('useConfirmDialog must be inside ConfirmDialogProvider');
  return value.confirm;
}

export function usePromptDialog() {
  const value = useContext(ConfirmDialogContext);
  if (!value) throw new Error('usePromptDialog must be inside ConfirmDialogProvider');
  return value.prompt;
}
