import { useRef, useState } from "react";
import PilotBankFields from "./PilotBankFields";
import { pilotButton, pilotInput } from "./pilotBankModel";
export default function PilotBankImport({ attempt, bank, url, busy, mutate }) {
  const fileInput = useRef(null);
  const [file, setFile] = useState(null);
  const [metadata, setMetadata] = useState({
    kind: "image",
    asset_kind: "lora",
    model_id: attempt.recipe.model_id,
    base_family: attempt.recipe.base_family,
    status: "unproven",
    provider: attempt.recipe.provider,
    endpoint: attempt.recipe.endpoint,
    notes: "",
    checkpoint: "",
    trigger: "",
    configuration_file_id: "",
    rights: "{}",
    storage_evidence: "{}",
    backup_evidence: "{}",
  });
  const importFile = async () => {
    if (!file) return;
    const data = new FormData();
    data.append("file", file);
    data.append(
      "metadata",
      JSON.stringify({
        kind: metadata.kind,
        asset_kind: ["weights", "config"].includes(metadata.kind)
          ? metadata.asset_kind
          : null,
        model_id: metadata.model_id,
        base_family: metadata.base_family,
        compatibility: {
          status: metadata.status,
          provider: metadata.provider,
          endpoint: metadata.endpoint,
        },
        notes: metadata.notes,
        checkpoint: metadata.checkpoint,
        trigger: metadata.trigger,
        configuration_file_id: metadata.configuration_file_id || null,
        rights: JSON.parse(metadata.rights),
        storage_evidence: JSON.parse(metadata.storage_evidence),
        backup_evidence: JSON.parse(metadata.backup_evidence),
      }),
    );
    const saved = await mutate(`${url}/files`, data);
    if (saved) {
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
    }
  };
  const configs = bank.attempts
    .flatMap((a) => a.outputs || [])
    .filter(
      (f) =>
        f.kind === "config" &&
        f.model_id === metadata.model_id &&
        f.base_family === metadata.base_family &&
        f.asset_kind === metadata.asset_kind,
    );
  return (
    <details>
      <summary className="cursor-pointer text-sm">
        Import returned local file
      </summary>
      <form
        className="pt-3 flex flex-col gap-3"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            await importFile();
          } catch (error) {
            mutate(null, null, error.message);
          }
        }}
      >
        <fieldset disabled={busy} className="min-w-0 flex flex-col gap-3">
          <label className="text-sm">
            Returned file
            <input
              className={pilotInput}
              type="file"
              ref={fileInput}
              onChange={(e) => setFile(e.target.files[0] || null)}
            />
          </label>
          <label className="text-sm">
            File kind
            <select
              className={pilotInput}
              value={metadata.kind}
              onChange={(e) =>
                setMetadata({ ...metadata, kind: e.target.value })
              }
            >
              {["image", "video", "weights", "config"].map((k) => (
                <option key={k}>{k}</option>
              ))}
            </select>
          </label>
          <PilotBankFields
            draft={metadata}
            onChange={(p) => setMetadata({ ...metadata, ...p })}
            fields={[
              ["model_id", "Asset model ID"],
              ["base_family", "Asset base family"],
              ["provider", "Asset provider"],
              ["endpoint", "Asset endpoint"],
              ["notes", "File notes", "textarea"],
              ["checkpoint", "Checkpoint / version"],
              ["trigger", "Asset trigger"],
            ]}
          />
          <label className="text-sm">
            Related configuration file
            <select
              className={pilotInput}
              value={metadata.configuration_file_id}
              onChange={(e) =>
                setMetadata({
                  ...metadata,
                  configuration_file_id: e.target.value,
                })
              }
            >
              <option value="">None</option>
              {configs.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.id} · {f.model_id}
                </option>
              ))}
            </select>
          </label>
          <details>
            <summary className="cursor-pointer text-sm">
              Advanced asset evidence
            </summary>
            {["weights", "config"].includes(metadata.kind) && (
              <label className="text-sm">
                Learned asset kind
                <select
                  className={pilotInput}
                  value={metadata.asset_kind}
                  onChange={(e) =>
                    setMetadata({ ...metadata, asset_kind: e.target.value })
                  }
                >
                  {["lora", "checkpoint", "refmod", "embedding", "other"].map(
                    (kind) => (
                      <option key={kind}>{kind}</option>
                    ),
                  )}
                </select>
              </label>
            )}
            <PilotBankFields
              draft={metadata}
              onChange={(p) => setMetadata({ ...metadata, ...p })}
              fields={[
                ["rights", "Asset rights JSON", "textarea"],
                [
                  "storage_evidence",
                  "Private storage evidence JSON",
                  "textarea",
                ],
                [
                  "backup_evidence",
                  "Backup / restore evidence JSON",
                  "textarea",
                ],
              ]}
            />
          </details>
          <label className="text-sm">
            Compatibility declaration
            <select
              className={pilotInput}
              value={metadata.status}
              onChange={(e) =>
                setMetadata({ ...metadata, status: e.target.value })
              }
            >
              <option value="unproven">Unproven</option>
              <option value="declared">
                Declared compatible (not verified)
              </option>
            </select>
          </label>
          <button
            type="submit"
            className={`${pilotButton} self-start`}
            disabled={!file}
          >
            Import file into private bank
          </button>
        </fieldset>
      </form>
    </details>
  );
}
