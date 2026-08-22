/** Return a new Set with `value` added when absent or removed when present. */
export function toggleInSet(current, value) {
  const next = new Set(current);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  return next;
}
