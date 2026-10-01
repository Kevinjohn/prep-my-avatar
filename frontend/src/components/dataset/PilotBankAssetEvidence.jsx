import PilotBankFields from "./PilotBankFields";
import PilotBankConflicts from "./PilotBankConflicts";
import { usePilotBankDraft } from "./pilotBankDraft";
import { pilotButton, pilotInput } from "./pilotBankModel";
export default function PilotBankAssetEvidence({ output, url, busy, mutate }) {
  const state = usePilotBankDraft({
    status: output.compatibility?.status || "unproven",
    provider: output.compatibility?.provider || "",
    endpoint: output.compatibility?.endpoint || "",
    rights: JSON.stringify(output.rights || {}, null, 2),
    storage_evidence: JSON.stringify(output.storage_evidence || {}, null, 2),
    backup_evidence: JSON.stringify(output.backup_evidence || {}, null, 2),
  });
  const { draft, setDraft, conflicts, resolve } = state;
  const conflict = Object.keys(conflicts).length > 0;
  const change = (patch) => setDraft({ ...draft, ...patch });
  const save = () => {
    if (conflict) return;
    const evidence = {};
    for (const key of ["rights", "storage_evidence", "backup_evidence"]) {
      const value = JSON.parse(draft[key]);
      if (!value || Array.isArray(value) || typeof value !== "object")
        throw new Error("Asset evidence must be JSON objects.");
      evidence[key] = value;
    }
    mutate(
      `${url}/metadata`,
      {
        compatibility: {
          status: draft.status,
          provider: draft.provider,
          endpoint: draft.endpoint,
        },
        ...evidence,
      },
      undefined,
      "PATCH",
    );
  };
  return (
    <details>
      <summary className="cursor-pointer text-sm">
        Update asset compatibility and evidence
      </summary>
      <p className="text-sm text-content-muted">
        Update declarations and storage records without importing again. File
        hash, model, base family and kind remain fixed; earlier attempts keep
        their captured inputs.
      </p>
      <form
        className="flex min-w-0 flex-col gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          try {
            save();
          } catch (error) {
            mutate(null, null, error.message);
          }
        }}
      >
        <PilotBankConflicts conflicts={conflicts} resolve={resolve} />
        <fieldset className="flex min-w-0 flex-col gap-3" disabled={busy}>
          <label className="text-sm">
            Saved asset compatibility
            <select
              className={pilotInput}
              value={draft.status}
              onChange={(e) => change({ status: e.target.value })}
            >
              <option value="unproven">Unproven</option>
              <option value="declared">
                Declared compatible (not verified)
              </option>
            </select>
          </label>
          <PilotBankFields
            draft={draft}
            onChange={change}
            fields={[
              ["provider", "Saved asset provider"],
              ["endpoint", "Saved asset endpoint"],
            ]}
          />
          <details>
            <summary className="cursor-pointer text-sm">
              Advanced saved asset evidence
            </summary>
            <PilotBankFields
              draft={draft}
              onChange={change}
              fields={[
                ["rights", "Saved asset rights JSON", "textarea"],
                [
                  "storage_evidence",
                  "Saved private storage evidence JSON",
                  "textarea",
                ],
                [
                  "backup_evidence",
                  "Saved backup / restore evidence JSON",
                  "textarea",
                ],
              ]}
            />
          </details>
          <button
            type="submit"
            className={`${pilotButton} self-start`}
            disabled={conflict}
          >
            Save asset evidence
          </button>
        </fieldset>
      </form>
    </details>
  );
}
