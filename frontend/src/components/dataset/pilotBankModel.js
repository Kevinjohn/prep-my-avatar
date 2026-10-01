export const pilotButton =
  "rounded border border-border bg-surface px-3 py-2 text-sm text-content disabled:opacity-40";
export const pilotInput =
  "block w-full min-w-0 rounded border border-border bg-surface px-2 py-2 text-sm text-content";
export function exportReferences(item) {
  return (item?.entries || [])
    .filter((e) => e.role === "reference")
    .sort((a, b) => (a.reference_order || 0) - (b.reference_order || 0))
    .map((e) => ({
      path: e.image_path,
      sha256: e.image_sha256,
      role: e.reference_role || "reference",
    }));
}
export function eligiblePilotFiles(bank, use) {
  return bank.attempts.flatMap((a) =>
    (a.outputs || [])
      .filter((f) =>
        use === "first_frame"
          ? f.kind === "image" && f.review?.accepted
          : ["weights", "config"].includes(f.kind),
      )
      .map((f) => ({ ...f, attempt_id: a.id, file_id: f.id })),
  );
}
export function createPilotDraft(
  bank,
  recipe = bank.recipes.find((item) => item.id === "manual-still") ||
    bank.recipes[0],
) {
  const item = bank.exports[0];
  return {
    export_revision: item?.revision || "",
    recipe_id: recipe?.id || "",
    process: recipe?.process || "still",
    provider: recipe?.provider || "",
    endpoint: recipe?.endpoint || "",
    model_id: recipe?.model_id || "",
    base_family: recipe?.base_family || "",
    parameters: JSON.stringify(recipe?.parameters || {}, null, 2),
    capabilities: JSON.stringify(recipe?.capabilities || {}, null, 2),
    documentation_url: recipe?.documentation_url || "",
    documentation_checked_at: recipe?.documentation_checked_at || "",
    provider_version_if_exposed: recipe?.provider_version_if_exposed || "",
    references: exportReferences(item),
    asset_inputs: [],
    first_frame: null,
    prompt: "",
    seed: "",
    status: "not_started",
    request_id: "",
    currency: "",
    estimated: "",
    reported_actual: "",
    notes: "",
    error: "",
  };
}
export function pilotCost(draft) {
  const number = (v) => {
    if (v === "" || v == null) return null;
    const n = Number(v);
    if (!Number.isFinite(n) || n < 0)
      throw new Error("Cost must be a finite nonnegative number.");
    return n;
  };
  return {
    currency: draft.currency || null,
    estimated: number(draft.estimated),
    reported_actual: number(draft.reported_actual),
  };
}
export function pilotPayload(draft, bank) {
  const item = bank.exports.find(
    (e) => String(e.revision) === String(draft.export_revision),
  );
  if (!item) throw new Error("Select an existing reviewed export.");
  const capabilities = JSON.parse(draft.capabilities || "{}");
  if (
    !capabilities ||
    Array.isArray(capabilities) ||
    typeof capabilities !== "object"
  )
    throw new Error("Capabilities must be a JSON object.");
  const parameters = JSON.parse(draft.parameters);
  if (
    !parameters ||
    Array.isArray(parameters) ||
    typeof parameters !== "object"
  )
    throw new Error("Parameters must be a JSON object.");
  const recipe = bank.recipes.find((r) => r.id === draft.recipe_id);
  const seed =
    draft.seed === "" || draft.seed == null ? null : Number(draft.seed);
  if (seed !== null && !Number.isSafeInteger(seed))
    throw new Error("Seed must be an exact integer.");
  return {
    version: bank.version,
    export_revision: item.revision,
    manifest_sha256: item.manifest_sha256,
    process: draft.process,
    recipe: {
      id: recipe.id,
      version: recipe.version,
      provider: draft.provider,
      endpoint: draft.endpoint,
      model_id: draft.model_id,
      base_family: draft.base_family,
      parameters,
      capabilities,
      documentation_url: draft.documentation_url || null,
      documentation_checked_at: draft.documentation_checked_at || null,
      provider_version_if_exposed: draft.provider_version_if_exposed || null,
    },
    references: draft.references,
    asset_inputs: draft.asset_inputs.map((a) => {
      const file = eligiblePilotFiles(bank, "asset").find(
        (f) => f.file_id === a.file_id,
      );
      const issue = file
        ? pilotAssetError(file, draft)
        : "Asset no longer available.";
      if (issue) throw new Error(issue);
      const strength = Number(a.strength);
      if (!Number.isFinite(strength) || strength < 0)
        throw new Error("Asset strength must be finite and nonnegative.");
      return {
        attempt_id: a.attempt_id,
        file_id: a.file_id,
        sha256: a.sha256,
        strength,
      };
    }),
    first_frame: draft.first_frame,
    prompt: draft.prompt,
    seed,
    status: draft.status,
    request_id: draft.request_id || null,
    cost: pilotCost(draft),
    notes: draft.notes,
    error: draft.error || null,
  };
}

export function pilotAssetError(file, draft) {
  let capabilities;
  try {
    capabilities = JSON.parse(draft.capabilities || "{}");
  } catch {
    return "Target capabilities JSON is invalid.";
  }
  if (file.compatibility?.status !== "declared")
    return "Compatibility has not been declared.";
  if (
    !capabilities.asset_kinds?.includes(file.asset_kind) ||
    !capabilities.asset_input_kinds?.includes(file.kind)
  )
    return "Target recipe does not declare support for this asset kind.";
  if (
    !(capabilities.accepted_asset_model_ids || [draft.model_id]).includes(
      file.model_id,
    ) ||
    file.base_family !== draft.base_family ||
    file.compatibility.provider !== draft.provider ||
    file.compatibility.endpoint !== draft.endpoint
  )
    return "Target model, base, provider or endpoint differs.";
  return "";
}
