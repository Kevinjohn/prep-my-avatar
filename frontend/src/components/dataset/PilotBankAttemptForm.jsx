import PilotBankReferences from "./PilotBankReferences";
import PilotBankFields from "./PilotBankFields";
import {
  createPilotDraft,
  eligiblePilotFiles,
  exportReferences,
  pilotButton,
  pilotInput,
  pilotAssetError,
} from "./pilotBankModel";
export default function PilotBankAttemptForm({
  bank,
  draft,
  onChange,
  onSave,
  busy,
}) {
  const change = (patch) => {
    const endpointChanged =
      Object.hasOwn(patch, "endpoint") && patch.endpoint !== draft.endpoint;
    onChange({
      ...draft,
      ...(endpointChanged
        ? {
            documentation_url: "",
            documentation_checked_at: "",
            provider_version_if_exposed: "",
          }
        : {}),
      ...patch,
    });
  };
  const frames = eligiblePilotFiles(bank, "first_frame");
  const assets = eligiblePilotFiles(bank, "asset");
  const item = bank.exports.find(
    (e) => String(e.revision) === String(draft.export_revision),
  );
  const refs = exportReferences(item);
  return (
    <form
      className="flex min-w-0 flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        onSave();
      }}
    >
      <h3 className="m-0 text-sm font-semibold">Record a manual attempt</h3>
      <fieldset disabled={busy} className="min-w-0 flex flex-col gap-3">
        <label className="text-sm text-content-muted">
          Reviewed export
          <select
            className={pilotInput}
            value={draft.export_revision}
            onChange={(e) =>
              change({
                export_revision: e.target.value,
                references: exportReferences(
                  bank.exports.find(
                    (x) => String(x.revision) === e.target.value,
                  ),
                ),
              })
            }
          >
            {bank.exports.map((x) => (
              <option key={x.revision} value={x.revision}>
                {x.subject?.name || "Subject"} · {x.revision}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm text-content-muted">
          Candidate recipe
          <select
            className={pilotInput}
            value={draft.recipe_id}
            onChange={(e) => {
              const recipe = bank.recipes.find((r) => r.id === e.target.value);
              const next = createPilotDraft(bank, recipe);
              change({
                recipe_id: next.recipe_id,
                process: next.process,
                provider: next.provider,
                endpoint: next.endpoint,
                model_id: next.model_id,
                base_family: next.base_family,
                parameters: next.parameters,
                capabilities: next.capabilities,
                documentation_url: next.documentation_url,
                documentation_checked_at: next.documentation_checked_at,
                provider_version_if_exposed: next.provider_version_if_exposed,
              });
            }}
          >
            {bank.recipes.map((r) => (
              <option key={r.id} value={r.id}>
                {r.label || r.id}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm text-content-muted">
          Process
          <select
            className={pilotInput}
            value={draft.process}
            onChange={(e) => change({ process: e.target.value })}
          >
            {["still", "video", "adaptation"].map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
        </label>
        <PilotBankFields
          draft={draft}
          onChange={change}
          fields={[
            ["provider", "Provider"],
            ["endpoint", "Endpoint"],
            ["model_id", "Model ID"],
            ["base_family", "Base family"],
            ["prompt", "Prompt / scene notes", "textarea"],
            ["seed", "Seed"],
          ]}
        />
        <PilotBankReferences draft={draft} refs={refs} change={change} />
        <label className="text-sm text-content-muted">
          Accepted first-frame still
          <select
            className={pilotInput}
            value={draft.first_frame?.file_id || ""}
            onChange={(e) => {
              const f = frames.find((x) => x.file_id === e.target.value);
              change({
                first_frame: f
                  ? {
                      attempt_id: f.attempt_id,
                      file_id: f.file_id,
                      sha256: f.sha256,
                    }
                  : null,
              });
            }}
          >
            <option value="">None</option>
            {frames.map((f) => (
              <option key={f.file_id} value={f.file_id}>
                {f.file_id}
              </option>
            ))}
          </select>
        </label>
        {draft.first_frame && (
          <p className="text-sm break-all">
            Accepted still from this dataset · SHA-256:{" "}
            {draft.first_frame.sha256}
          </p>
        )}
        <fieldset className="min-w-0">
          <legend className="text-sm">Reusable model assets</legend>
          {assets.length === 0 && (
            <p className="text-sm text-content-muted">
              Import weights or configuration files below to reuse them.
            </p>
          )}
          {assets.map((f) => {
            const assetError = pilotAssetError(f, draft);
            const selected = draft.asset_inputs.find(
              (a) => a.file_id === f.file_id,
            );
            return (
              <div
                key={f.file_id}
                className="flex flex-wrap items-center gap-2 text-sm"
              >
                <label className="break-all">
                  <input
                    type="checkbox"
                    checked={Boolean(selected)}
                    disabled={Boolean(assetError) && !selected}
                    onChange={(e) =>
                      change({
                        asset_inputs: e.target.checked
                          ? [
                              ...draft.asset_inputs,
                              {
                                attempt_id: f.attempt_id,
                                file_id: f.file_id,
                                sha256: f.sha256,
                                strength: 1,
                              },
                            ]
                          : draft.asset_inputs.filter(
                              (a) => a.file_id !== f.file_id,
                            ),
                      })
                    }
                  />{" "}
                  {f.kind} / {f.asset_kind || "unspecified"} · {f.model_id} ·{" "}
                  {f.base_family} · {f.file_id} · SHA-256: {f.sha256} ·
                  compatibility {f.compatibility?.status || "unproven"}
                </label>
                {assetError && (
                  <span className="text-content-muted">{assetError}</span>
                )}
                {selected && (
                  <label>
                    Strength
                    <input
                      className={pilotInput}
                      type="number"
                      step="any"
                      value={selected.strength}
                      onChange={(e) =>
                        change({
                          asset_inputs: draft.asset_inputs.map((a) =>
                            a.file_id === f.file_id
                              ? { ...a, strength: e.target.value }
                              : a,
                          ),
                        })
                      }
                    />
                  </label>
                )}
              </div>
            );
          })}
        </fieldset>
        <details>
          <summary className="cursor-pointer text-sm">
            Advanced parameters
          </summary>
          <PilotBankFields
            draft={draft}
            onChange={change}
            fields={[
              ["parameters", "Parameters JSON", "textarea"],
              ["capabilities", "Target capabilities JSON", "textarea"],
              ["documentation_url", "Recipe documentation URL"],
              ["documentation_checked_at", "Documentation checked at"],
              ["provider_version_if_exposed", "Provider version if exposed"],
            ]}
          />
        </details>
        <button type="submit" className={`${pilotButton} self-start`}>
          Record attempt
        </button>
      </fieldset>
    </form>
  );
}
