import { usePilotBankDraft } from "./pilotBankDraft";
import PilotBankConflicts from "./PilotBankConflicts";
import PilotBankFields from "./PilotBankFields";
import PilotBankHeldOut from "./PilotBankHeldOut";
import PilotBankImport from "./PilotBankImport";
import PilotBankOutput from "./PilotBankOutput";
import { pilotButton, pilotCost, pilotInput } from "./pilotBankModel";
export default function PilotBankAttempt({
  attempt,
  bank,
  base,
  tools,
  busy,
  mutate,
}) {
  const controlState = usePilotBankDraft(attempt.controls || {});
  const controls = controlState.draft;
  const setControls = controlState.setDraft;
  const runState = usePilotBankDraft({
    status: attempt.status,
    request_id: attempt.request_id,
    notes: attempt.notes,
    error: attempt.error,
    currency: attempt.cost?.currency || "",
    estimated: attempt.cost?.estimated ?? "",
    reported_actual: attempt.cost?.reported_actual ?? "",
  });
  const { draft, setDraft } = runState;
  const hasConflict =
    Object.keys(runState.conflicts).length > 0 ||
    Object.keys(controlState.conflicts).length > 0;
  const url = `${base}/attempts/${encodeURIComponent(attempt.id)}`;
  const update = (p) => setDraft({ ...draft, ...p });
  const reconcile = () => {
    if (hasConflict) return;
    return mutate(
      url,
      {
        status: draft.status,
        request_id: draft.request_id,
        notes: draft.notes,
        error: draft.error,
        cost: pilotCost(draft),
        controls,
      },
      undefined,
      "PATCH",
    );
  };
  return (
    <article className="min-w-0 rounded border border-border p-3 flex flex-col gap-3">
      <h3 className="m-0 text-sm font-semibold break-all">
        {attempt.process} · {attempt.status} · {attempt.id}
      </h3>
      <details>
        <summary className="cursor-pointer text-sm">
          Exact captured settings and inputs
        </summary>
        <pre className="whitespace-pre-wrap break-all text-xs">
          {JSON.stringify(
            {
              export_revision: attempt.export_revision,
              manifest_sha256: attempt.manifest_sha256,
              recipe: attempt.recipe,
              references: attempt.references,
              asset_inputs: attempt.asset_inputs,
              first_frame: attempt.first_frame,
              prompt: attempt.prompt,
              seed: attempt.seed,
              controls: attempt.controls,
            },
            null,
            2,
          )}
        </pre>
      </details>
      <details>
        <summary className="cursor-pointer text-sm">
          Reconcile manual run
        </summary>
        <form
          className="pt-3 flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            try {
              reconcile();
            } catch (error) {
              mutate(null, null, error.message);
            }
          }}
        >
          <PilotBankConflicts
            conflicts={runState.conflicts}
            resolve={runState.resolve}
          />
          <PilotBankConflicts
            conflicts={controlState.conflicts}
            resolve={controlState.resolve}
          />
          <fieldset disabled={busy} className="min-w-0 flex flex-col gap-3">
            <label className="text-sm">
              Attempt status
              <select
                className={pilotInput}
                value={draft.status}
                onChange={(e) => update({ status: e.target.value })}
              >
                {[
                  "not_started",
                  "submitted",
                  "succeeded",
                  "failed",
                  "unknown",
                ].map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </label>
            <PilotBankFields
              draft={draft}
              onChange={update}
              fields={[
                ["request_id", "Request ID"],
                ["currency", "Cost currency"],
                ["estimated", "Estimated cost", "number"],
                ["reported_actual", "Reported actual cost", "number"],
                ["error", "Run error", "textarea"],
                ["notes", "Run notes", "textarea"],
              ]}
            />
            <details>
              <summary className="cursor-pointer text-sm">
                Adapter application controls
              </summary>
              <div className="flex flex-col gap-3 pt-3">
                {[
                  [
                    "paired_without_adapter_attempt_id",
                    "Paired attempt without adapter",
                  ],
                  [
                    "paired_with_adapter_attempt_id",
                    "Paired attempt with adapter",
                  ],
                ].map(([key, label]) => (
                  <label key={key} className="text-sm">
                    {label}
                    <select
                      className={pilotInput}
                      value={controls[key] || ""}
                      onChange={(e) =>
                        setControls({
                          ...controls,
                          [key]: e.target.value || null,
                        })
                      }
                    >
                      <option value="">None</option>
                      {bank.attempts.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.process} · {a.id}
                        </option>
                      ))}
                    </select>
                  </label>
                ))}
                <PilotBankFields
                  draft={controls}
                  onChange={(p) => setControls({ ...controls, ...p })}
                  fields={[
                    [
                      "application_evidence",
                      "Adapter application evidence",
                      "textarea",
                    ],
                  ]}
                />
                <p className="text-sm text-content-muted">
                  Paired runs and notes record evidence; they do not
                  automatically verify application.
                </p>
              </div>
            </details>
            <button
              type="submit"
              disabled={hasConflict}
              className={`${pilotButton} self-start`}
            >
              Save run details
            </button>
          </fieldset>
        </form>
      </details>
      <PilotBankHeldOut attempt={attempt} bank={bank} base={base} />
      <PilotBankImport
        attempt={attempt}
        bank={bank}
        url={url}
        busy={busy}
        mutate={mutate}
      />
      {(attempt.outputs || []).map((output) => (
        <PilotBankOutput
          key={output.id}
          output={output}
          attemptId={attempt.id}
          base={base}
          tools={tools}
          busy={busy}
          mutate={mutate}
        />
      ))}
    </article>
  );
}
