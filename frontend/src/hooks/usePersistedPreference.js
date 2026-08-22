import { useEffect, useState } from 'react';

const readString = (value) => value;
const writeString = (value) => String(value);

/** Own a best-effort localStorage preference with one lazy read and writes on change. */
export function usePersistedPreference(
  key,
  fallback,
  { parse = readString, serialize = writeString } = {},
) {
  const [value, setValue] = useState(() => {
    try {
      const stored = globalThis.localStorage.getItem(key);
      return stored === null ? fallback : parse(stored);
    } catch {
      return fallback;
    }
  });

  useEffect(() => {
    try {
      globalThis.localStorage.setItem(key, serialize(value));
    } catch { /* preference is best-effort */ }
  }, [key, serialize, value]);

  return { value, setValue };
}
