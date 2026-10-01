import { pilotButton } from "./pilotBankModel";
export default function PilotBankReferences({ draft, refs, change }) {
  return (
    <fieldset className="min-w-0">
      <legend className="text-sm">Ordered export references</legend>
      <p className="text-sm text-content-muted">
        Only reference photos are offered. Evaluation photos remain separate.
      </p>
      {refs.map((r) => (
        <label key={r.path} className="flex min-w-0 items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={draft.references.some((x) => x.path === r.path)}
            onChange={(e) =>
              change({
                references: e.target.checked
                  ? [...draft.references, r]
                  : draft.references.filter((x) => x.path !== r.path),
              })
            }
          />
          <span className="break-all">
            {r.role} · {r.path}
          </span>
        </label>
      ))}
      <ol className="list-decimal pl-5">
        {draft.references.map((r, i) => (
          <li key={r.path} className="text-sm break-all">
            {r.role}{" "}
            <button
              type="button"
              className={pilotButton}
              disabled={i === 0}
              aria-label={`Move reference ${i + 1} earlier`}
              onClick={() => {
                const next = [...draft.references];
                [next[i - 1], next[i]] = [next[i], next[i - 1]];
                change({ references: next });
              }}
            >
              Earlier
            </button>
          </li>
        ))}
      </ol>
    </fieldset>
  );
}
