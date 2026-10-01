import { pilotButton } from "./pilotBankModel";
export default function PilotBankConflicts({ conflicts, resolve }) {
  return (
    <>
      {Object.entries(conflicts).map(([key, value]) => (
        <div key={key} role="alert" className="flex flex-wrap gap-2 text-sm">
          <p className="w-full m-0 break-all">
            Saved {key.replaceAll("_", " ")} changed while you were editing.
            Updated value: {JSON.stringify(value)}
          </p>
          <button
            type="button"
            className={pilotButton}
            onClick={() => resolve(key, false)}
          >
            Keep my {key.replaceAll("_", " ")}
          </button>
          <button
            type="button"
            className={pilotButton}
            onClick={() => resolve(key, true)}
          >
            Use updated {key.replaceAll("_", " ")}
          </button>
        </div>
      ))}
    </>
  );
}
