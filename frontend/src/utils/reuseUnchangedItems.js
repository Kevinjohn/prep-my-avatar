function valuesEqual(left, right) {
  if (Object.is(left, right)) return true;
  if (!left || !right || typeof left !== 'object' || typeof right !== 'object') {
    return false;
  }
  if (Array.isArray(left) !== Array.isArray(right)) return false;
  const leftKeys = Object.keys(left);
  const rightKeys = Object.keys(right);
  if (leftKeys.length !== rightKeys.length) return false;
  return leftKeys.every((key) => Object.prototype.hasOwnProperty.call(right, key)
    && valuesEqual(left[key], right[key]));
}

/** Reuse prior JSON-row identities when an API refresh returns unchanged fields. */
export function reuseUnchangedItems(previous, incoming, key = 'id') {
  if (!previous?.length || !incoming?.length) return incoming;
  const previousByKey = new Map(previous.map((item) => [item[key], item]));
  let sameArray = previous.length === incoming.length;
  const reconciled = incoming.map((item, index) => {
    const prior = previousByKey.get(item[key]);
    const value = prior && valuesEqual(prior, item) ? prior : item;
    if (value !== previous[index]) sameArray = false;
    return value;
  });
  return sameArray ? previous : reconciled;
}
