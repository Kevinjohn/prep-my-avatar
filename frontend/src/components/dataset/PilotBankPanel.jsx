import { useEffect, useRef, useState } from "react";
import { apiFetch, apiResponse, getCsrfToken } from "../../api/fetchClient";
import PilotBankAttemptForm from "./PilotBankAttemptForm";
import PilotBankAttempt from "./PilotBankAttempt";
import { createPilotDraft, pilotPayload, pilotButton } from "./pilotBankModel";
export default function PilotBankPanel({ datasetId }) {
  const [open, setOpen] = useState(false);
  const [bank, setBank] = useState(null);
  const [draft, setDraft] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [conflict, setConflict] = useState(false);
  const lifecycle = useRef(0);
  const lock = useRef(false);
  const base = `/api/dataset/${datasetId}/pilot-bank`;
  useEffect(() => {
    const token = ++lifecycle.current;
    if (!open) return;
    setBusy(true);
    lock.current = true;
    setError("");
    apiFetch(base)
      .then((value) => {
        if (token === lifecycle.current) {
          setBank(value);
          setDraft((current) => current || createPilotDraft(value));
          setConflict(false);
        }
      })
      .catch((e) => {
        if (token === lifecycle.current) setError(e.message);
      })
      .finally(() => {
        if (token === lifecycle.current) {
          setBusy(false);
          lock.current = false;
        }
      });
    return () => {
      lifecycle.current += 1;
      lock.current = false;
    };
  }, [base, open, reload]);
  const mutate = async (url, payload, validationError, method = "POST") => {
    if (validationError) {
      setError(validationError);
      return;
    }
    if (lock.current || conflict) return;
    const token = lifecycle.current;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      const form = payload instanceof FormData;
      if (form) payload.set("version", String(bank.version));
      const next = await apiFetch(url, {
        method,
        headers: form
          ? { "X-CSRFToken": getCsrfToken() }
          : {
              "Content-Type": "application/json",
              "X-CSRFToken": getCsrfToken(),
            },
        body: form
          ? payload
          : JSON.stringify({ ...payload, version: bank.version }),
      });
      if (token === lifecycle.current) {
        setBank(next);
        if (url === `${base}/attempts`) setDraft(createPilotDraft(next));
        return true;
      }
    } catch (e) {
      if (token === lifecycle.current) {
        setError(e.message);
        if (e.status === 409) setConflict(true);
      }
    } finally {
      if (token === lifecycle.current) {
        setBusy(false);
        lock.current = false;
      }
    }
  };
  const save = () => {
    try {
      mutate(`${base}/attempts`, pilotPayload(draft, bank));
    } catch (e) {
      setError(e.message);
    }
  };
  const download = async () => {
    if (lock.current) return;
    const token = lifecycle.current;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      const response = await apiResponse(`${base}/download`);
      const blob = await response.blob();
      if (token !== lifecycle.current) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "private_person_asset_bank.zip";
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      if (token === lifecycle.current) setError(e.message);
    } finally {
      if (token === lifecycle.current) {
        setBusy(false);
        lock.current = false;
      }
    }
  };
  return (
    <section
      aria-label="Private asset bank"
      className="min-w-0 rounded-lg border border-border bg-surface px-3 py-3 flex flex-col gap-3 text-content"
    >
      <h2 className="m-0 text-base font-semibold">Private asset bank</h2>
      <p className="m-0 text-sm text-content-muted">
        Record manual attempts, imported outputs, reusable model assets and
        reviews locally. This panel does not submit hosted jobs. Ordinary corpus
        backups exclude this bank; download it separately.
      </p>
      <button
        type="button"
        className={`${pilotButton} self-start`}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {open ? "Close private asset bank" : "Open private asset bank"}
      </button>
      <div hidden={!open} className="flex min-w-0 flex-col gap-3">
        {busy && (
          <p role="status" className="m-0 text-sm">
            Working…
          </p>
        )}
        {error && (
          <p role="alert" className="m-0 text-sm">
            {error}
            {conflict &&
              " Bank changed. Reload before making another change; the rejected action will not be resubmitted."}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className={pilotButton}
            disabled={busy}
            onClick={() => setReload(reload + 1)}
          >
            Reload private bank
          </button>
          {bank && (
            <button
              type="button"
              className={pilotButton}
              disabled={busy}
              onClick={download}
            >
              Download private asset bank
            </button>
          )}
        </div>
        <p className="m-0 text-sm text-content-muted">
          Unsaved edits stay in this panel when you close or reload it. Reload
          refreshes saved evidence; review your retained edits before saving
          again.
        </p>
        {bank && draft && (
          <>
            {bank.exports.length === 0 ? (
              <p role="status" className="text-sm">
                Create a reviewed hosted export first, then reload this bank.
              </p>
            ) : (
              <PilotBankAttemptForm
                bank={bank}
                draft={draft}
                onChange={setDraft}
                onSave={save}
                busy={busy || conflict}
              />
            )}
            {bank.attempts.length === 0 && (
              <p className="text-sm text-content-muted">
                No attempts recorded yet. Failed and unknown runs can be
                retained too.
              </p>
            )}
            {bank.attempts.map((attempt) => (
              <PilotBankAttempt
                key={attempt.id}
                attempt={attempt}
                bank={bank}
                base={base}
                tools={bank.tools}
                busy={busy || conflict}
                mutate={mutate}
              />
            ))}
          </>
        )}
      </div>
    </section>
  );
}
