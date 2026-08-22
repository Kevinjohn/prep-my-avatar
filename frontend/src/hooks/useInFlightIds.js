import { useState } from 'react';

/**
 * Track which rows have a request in flight, and refuse a second one.
 *
 * The two atomic side-by-side resolvers (small-image rescue, reconstruction
 * review) each wrote this out: a `Set` of ids, added before the await and
 * removed in a `finally`, with an early return when the id is already in it.
 * The `finally` is the part worth having one copy of — without it a request
 * that throws leaves that row disabled for the life of the panel, with no way
 * back but a reload.
 *
 * Returns `{ inFlight, run }`. `run(id, work)` is a no-op if `id` is already in
 * flight, so a caller can hand it a click handler directly and disable the row
 * on `inFlight.has(id)`. An object rather than a `useState`-style pair because
 * `tsconfig.check.json` runs `checkJs`, under which a returned array literal
 * infers as `(Set | function)[]` and every call site then fails to typecheck.
 */
export function useInFlightIds() {
  const [inFlight, setInFlight] = useState(() => new Set());

  const run = async (id, work) => {
    if (inFlight.has(id)) return;
    setInFlight((current) => new Set(current).add(id));
    try {
      await work();
    } finally {
      setInFlight((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
    }
  };

  return { inFlight, run };
}
