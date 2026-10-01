import test from "node:test";
import assert from "node:assert/strict";
import {
  createPilotDraft,
  pilotPayload,
  eligiblePilotFiles,
  exportReferences,
} from "./pilotBankModel.js";
const bank = {
  version: 3,
  exports: [
    {
      revision: "r1",
      manifest_sha256: "hash",
      entries: [
        { role: "evaluation", image_path: "eval", image_sha256: "e" },
        {
          role: "reference",
          image_path: "ref",
          image_sha256: "r",
          reference_order: 1,
        },
      ],
    },
  ],
  recipes: [
    {
      id: "manual",
      version: 1,
      process: "still",
      provider: "manual",
      parameters: { steps: 4 },
    },
  ],
  attempts: [
    {
      id: "a",
      outputs: [
        { id: "ok", kind: "image", sha256: "s", review: { accepted: true } },
        { id: "no", kind: "image", review: { accepted: false } },
        {
          id: "weights",
          kind: "weights",
          asset_kind: "lora",
          sha256: "w",
          model_id: "m",
          base_family: "b",
          compatibility: { status: "declared", provider: "p", endpoint: "e" },
        },
      ],
    },
  ],
};
test("new attempt starts from pinned export and recipe without evaluation references", () => {
  const draft = createPilotDraft(bank);
  assert.equal(draft.export_revision, "r1");
  assert.deepEqual(
    exportReferences(bank.exports[0]).map((r) => r.path),
    ["ref"],
  );
  assert.equal(pilotPayload(draft, bank).version, 3);
  assert.equal(pilotPayload(draft, bank).status, "not_started");
});
test("parameters must be a JSON object and costs must be finite nonnegative numbers", () => {
  const draft = createPilotDraft(bank);
  assert.throws(
    () => pilotPayload({ ...draft, parameters: "[]" }, bank),
    /object/,
  );
  assert.throws(
    () => pilotPayload({ ...draft, estimated: "-1" }, bank),
    /cost/i,
  );
});
test("first frames only offer accepted images, model inputs retain hash and strength", () => {
  assert.deepEqual(
    eligiblePilotFiles(bank, "first_frame").map((f) => f.file_id),
    ["ok"],
  );
  const draft = {
    ...createPilotDraft(bank),
    model_id: "m",
    base_family: "b",
    provider: "p",
    endpoint: "e",
    capabilities: JSON.stringify({
      asset_kinds: ["lora"],
      asset_input_kinds: ["weights"],
    }),
  };
  draft.asset_inputs = [
    { attempt_id: "a", file_id: "weights", sha256: "w", strength: "0.8" },
  ];
  assert.equal(pilotPayload(draft, bank).asset_inputs[0].strength, 0.8);
});
test("seed captures exact integers including zero and rejects fractional input", () => {
  const draft = createPilotDraft(bank);
  assert.equal(pilotPayload({ ...draft, seed: "0" }, bank).seed, 0);
  assert.equal(pilotPayload({ ...draft, seed: "" }, bank).seed, null);
  assert.throws(() => pilotPayload({ ...draft, seed: "2.4" }, bank), /Seed/);
});

test("reuse rejects mismatched target and unsupported learned asset kinds", () => {
  const draft = {
    ...createPilotDraft(bank),
    model_id: "m",
    base_family: "b",
    provider: "p",
    endpoint: "e",
    capabilities: JSON.stringify({
      asset_kinds: ["lora"],
      asset_input_kinds: ["weights"],
    }),
    asset_inputs: [
      { attempt_id: "a", file_id: "weights", sha256: "w", strength: 1 },
    ],
  };
  assert.throws(
    () => pilotPayload({ ...draft, model_id: "other" }, bank),
    /differs/,
  );
  assert.throws(
    () => pilotPayload({ ...draft, capabilities: "{}" }, bank),
    /support/,
  );
});

test("target capabilities explicitly allow a different learned source model", () => {
  const draft = {
    ...createPilotDraft(bank),
    model_id: "turbo",
    base_family: "b",
    provider: "p",
    endpoint: "e",
    capabilities: JSON.stringify({
      asset_kinds: ["lora"],
      asset_input_kinds: ["weights"],
      accepted_asset_model_ids: ["m"],
    }),
    asset_inputs: [
      { attempt_id: "a", file_id: "weights", sha256: "w", strength: 1 },
    ],
  };
  assert.equal(pilotPayload(draft, bank).asset_inputs[0].file_id, "weights");
  assert.equal(pilotPayload(draft, bank).recipe.model_id, "turbo");
});
test("new attempt prefers the maintained still recipe regardless of recipe ordering", () => {
  const recipes = [
    { id: "manual-adaptation", process: "adaptation" },
    { id: "manual-still", process: "still", parameters: { resolution: "1K" } },
  ];
  assert.equal(
    createPilotDraft({ ...bank, recipes }).recipe_id,
    "manual-still",
  );
});
