import { pilotInput } from "./pilotBankModel";
export default function PilotBankFields({
  draft,
  onChange,
  disabled = false,
  fields,
}) {
  return (
    <div className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
      {fields.map(([name, label, type = "text"]) => (
        <label key={name} className="min-w-0 text-sm text-content-muted">
          {label}
          {type === "textarea" ? (
            <textarea
              className={pilotInput}
              value={draft[name] ?? ""}
              disabled={disabled}
              onChange={(e) => onChange({ [name]: e.target.value })}
            />
          ) : (
            <input
              className={pilotInput}
              type={type}
              min={type === "number" ? "0" : undefined}
              step={type === "number" ? "any" : undefined}
              value={draft[name] ?? ""}
              disabled={disabled}
              onChange={(e) => onChange({ [name]: e.target.value })}
            />
          )}
        </label>
      ))}
    </div>
  );
}
