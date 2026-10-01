import { useEffect, useState } from "react";
const stableJson = (value) =>
  Array.isArray(value)
    ? value.map(stableJson)
    : value && typeof value === "object"
      ? Object.fromEntries(
          Object.keys(value)
            .sort()
            .map((key) => [key, stableJson(value[key])]),
        )
      : value;
const equal = (key, a, b) => {
  if (
    ["rights", "storage_evidence", "backup_evidence", "timed"].includes(key)
  ) {
    try {
      return (
        JSON.stringify(stableJson(JSON.parse(a))) ===
        JSON.stringify(stableJson(JSON.parse(b)))
      );
    } catch {
      return a === b;
    }
  }
  if (["estimated", "reported_actual", "correction_minutes"].includes(key)) {
    const normalize = (value) =>
      value === "" || value == null ? null : Number(value);
    return Object.is(normalize(a), normalize(b));
  }
  return JSON.stringify(a) === JSON.stringify(b);
};
export function mergePilotDraft(
  previous,
  draft,
  incoming,
  existingConflicts = {},
) {
  const merged = { ...draft };
  const conflicts = {};
  for (const key of Object.keys(incoming)) {
    if (equal(key, draft[key], previous[key])) merged[key] = incoming[key];
    else if (
      (!equal(key, incoming[key], previous[key]) ||
        Object.hasOwn(existingConflicts, key)) &&
      !equal(key, draft[key], incoming[key])
    )
      conflicts[key] = incoming[key];
  }
  return { draft: merged, conflicts };
}
export function usePilotBankDraft(incoming) {
  const serialized = JSON.stringify(incoming);
  const [state, setState] = useState({
    draft: incoming,
    baseline: incoming,
    conflicts: {},
  });
  useEffect(() => {
    const next = JSON.parse(serialized);
    setState((current) => {
      const result = mergePilotDraft(
        current.baseline,
        current.draft,
        next,
        current.conflicts,
      );
      return {
        draft: result.draft,
        baseline: next,
        conflicts: result.conflicts,
      };
    });
  }, [serialized]);
  const setDraft = (value) =>
    setState((current) => ({
      ...current,
      draft: typeof value === "function" ? value(current.draft) : value,
    }));
  const resolve = (key, useSaved) =>
    setState((current) => {
      const conflicts = { ...current.conflicts };
      delete conflicts[key];
      return {
        ...current,
        draft: useSaved
          ? { ...current.draft, [key]: current.conflicts[key] }
          : current.draft,
        conflicts,
      };
    });
  return { draft: state.draft, setDraft, conflicts: state.conflicts, resolve };
}
