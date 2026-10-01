export function hostedRoles(recipe) {
  return recipe?.supported_roles || ['training', 'reference', 'evaluation'];
}
export function hostedRoleMinima(recipe) {
  const requirements = recipe?.input_requirements || {};
  return { ...requirements.minimum_images_by_role,
    ...(requirements.minimum_training_images != null ? { training: requirements.minimum_training_images } : {}) };
}
export function changeHostedRecipe(draft, recipe) {
  return { ...draft, recipe_id: recipe.id, recipe_version: recipe.version, parameters: { ...recipe.defaults },
    selections: draft.selections.filter((entry) => hostedRoles(recipe).includes(entry.role)).map((entry) => {
      const { approval: _approval, preview: _preview, crop_box: _box, ...rest } = entry;
      return { ...rest, crop: null };
    }) };
}

/** Hosted drafts describe derivatives; they never edit the master corpus. */
export function createHostedDraft(snapshot) {
  const recipe = snapshot.recipes[0];
  return { dataset_revision: snapshot.dataset_revision, recipe_id: recipe.id,
    recipe_version: recipe.version, parameters: { ...recipe.defaults },
    subject: { ...snapshot.subject, consent: false, rights_basis: '', publication_scope: '' }, selections: [] };
}
export function reviewKey(draft, entry) {
  const { approval: _approval, preview: _preview, ...selection } = entry;
  return JSON.stringify([draft.dataset_revision, draft.recipe_id, draft.recipe_version,
    draft.parameters, draft.subject, selection]);
}
export function updateHostedSelection(draft, index, patch) {
  return { ...draft, selections: draft.selections.map((entry, i) => {
    if (i !== index) return entry;
    const { approval: _approval, preview: _preview, ...rest } = entry;
    return { ...rest, ...patch };
  }) };
}
export function squareCrop(image, box) {
  const { width, height } = image;
  const { left, top, side } = box;
  if (![width, height, left, top, side].every(Number.isFinite) || side <= 0 || left < 0 || top < 0 || left + side > width || top + side > height) return null;
  return [left / width, top / height, (left + side) / width, (top + side) / height];
}
export function hostedExportErrors(draft, snapshot) {
  const errors = [];
  if (draft.dataset_revision !== snapshot.dataset_revision) errors.push('The dataset changed. Reload the hosted draft and review again.');
  if (!draft.subject.name.trim() || !draft.subject.trigger_word.trim()) errors.push('Enter the subject name and trigger word.');
  if (!draft.subject.consent) errors.push('Confirm identifiable-person consent.');
  if (!draft.subject.rights_basis) errors.push('Choose a rights basis.');
  if (!draft.subject.publication_scope.trim()) errors.push('Describe the intended publication scope.');
  const recipe = snapshot.recipes.find((item) => item.id === draft.recipe_id && item.version === draft.recipe_version);
  if (!recipe) errors.push('Choose a supported recipe version.');
  const minima = hostedRoleMinima(recipe);
  if (!Object.keys(minima).length) errors.push('The recipe is missing valid role minima.');
  for (const [role, minimum] of Object.entries(minima)) {
    if (!hostedRoles(recipe).includes(role) || !Number.isInteger(minimum) || minimum < 0) errors.push('The recipe is missing valid role minima.');
    else if (draft.selections.filter((entry) => entry.role === role).length < minimum) errors.push(`Choose at least ${minimum} ${role} photo(s).`);
  }
  for (const [name, rule] of Object.entries(recipe?.parameters || {})) {
    const value = draft.parameters[name];
    if ((rule.enum && !rule.enum.includes(value)) || (rule.type === 'integer' && !Number.isInteger(value)) || (rule.type === 'number' && !Number.isFinite(value)) || (rule.type === 'boolean' && typeof value !== 'boolean') || (rule.minimum != null && value < rule.minimum) || (rule.maximum != null && value > rule.maximum)) errors.push(`Check recipe parameter: ${name}.`);
  }
  const creation = draft.selections.filter((entry) => entry.role !== 'evaluation');
  const evaluations = draft.selections.filter((entry) => entry.role === 'evaluation');
  const imageFor = (id) => snapshot.images.find((image) => image.id === id);
  for (const entry of draft.selections) {
    const image = imageFor(entry.image_id);
    if (!hostedRoles(recipe).includes(entry.role)) errors.push(`Photo ${entry.image_id} has an unsupported role for this recipe.`);
    if (entry.crop_box && !squareCrop(image || {}, entry.crop_box)) errors.push(`Photo ${entry.image_id} has an invalid square crop.`);
    if (image?.role_exclusions?.[entry.role]) errors.push(`Photo ${entry.image_id}: ${image.role_exclusions[entry.role]}`);
    if (!image || !image.eligible) errors.push(`Photo ${entry.image_id} is excluded by admission or rights rules.`);
    if (entry.role === 'reference' && image?.anchor_decision === 'excluded') errors.push(`Photo ${entry.image_id} is excluded from provider references.`);
    if (entry.role === 'reference' && (!entry.reference_role?.trim() || !Number.isInteger(entry.reference_order) || entry.reference_order < 1)) errors.push(`Give reference photo ${entry.image_id} a purpose and positive order.`);
    if (!entry.approval?.image_sha256 || !entry.approval?.caption_sha256 || !entry.approval?.pair_sha256 || entry.approval.key !== reviewKey(draft, entry)) errors.push(`Photo ${entry.image_id} (${entry.role}) needs exact crop and caption review.`);
    if (entry.role === 'evaluation') {
      for (const other of creation) {
        const sibling = imageFor(other.image_id);
        if (other.image_id === entry.image_id || (image?.original_lineage && JSON.stringify(image.original_lineage) === JSON.stringify(sibling?.original_lineage))) errors.push(`Evaluation photo ${entry.image_id} shares a source family with training or references.`);
        if ((entry.burst_group && entry.burst_group === other.burst_group) || (image?.duplicate_group && image.duplicate_group === sibling?.duplicate_group)) errors.push(`Evaluation photo ${entry.image_id} shares a burst group with training or references.`);
      }
    }
  }
  const orders = draft.selections.filter((entry) => entry.role === 'reference').map((entry) => entry.reference_order);
  if (new Set(orders).size !== orders.length) errors.push('Reference orders must be unique.');
  if (evaluations.length && !creation.length) errors.push('Choose creation photos separately from evaluation.');
  return [...new Set(errors)];
}
export function hostedExportPayload(draft, snapshot) {
  const entries = [...draft.selections.filter((entry) => entry.role !== 'reference'), ...draft.selections.filter((entry) => entry.role === 'reference').sort((a, b) => a.reference_order - b.reference_order)];
  return { dataset_revision: draft.dataset_revision, recipe_id: draft.recipe_id,
    recipe_version: draft.recipe_version, parameters: draft.parameters, subject: draft.subject,
    selections: entries.map(({ approval, preview: _preview, reference_order: _order, crop_box: _box, ...entry }) => ({ ...entry,
      approved_image_sha256: approval?.image_sha256, approved_caption_sha256: approval?.caption_sha256, approved_pair_sha256: approval?.pair_sha256 })),
    excluded_image_ids: snapshot.images.filter((image) => !entries.some((entry) => entry.image_id === image.id)).map((image) => image.id) };
}
