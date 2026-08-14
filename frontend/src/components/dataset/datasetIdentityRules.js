// When a dataset's identity fields are complete enough for the server to accept.
//
// This mirrors the server rule EXACTLY (POST /api/dataset/create, and the
// settings update that follows the same contract): a name is always required;
// a concept needs its description; and a trigger word is required for character
// and concept — it is the token that summons them — but NOT for style, where the
// server auto-generates a zsty_<id> placeholder, which is why the style form
// says there is no trigger to type.
//
// Both the create form and the settings modal ask this question. They used to
// each spell the rule out, with the same three clauses in a different order, so
// a change to the contract had two places to land and no way to notice it had
// only landed in one. Getting it wrong is not cosmetic: it enables a button
// whose request the server rejects with a bare 400 — no toast, no explanation.
export function datasetIdentityComplete({ name, trigger, description, isConcept, isStyle }) {
  return Boolean((name || '').trim())
    && (!isConcept || Boolean((description || '').trim()))
    && (isStyle || Boolean((trigger || '').trim()));
}
