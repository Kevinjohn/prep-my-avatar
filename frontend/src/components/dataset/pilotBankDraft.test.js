import test from "node:test";
import assert from "node:assert/strict";
import { mergePilotDraft } from "./pilotBankDraft.js";
test("reload refreshes untouched status while preserving edited notes", () => {
  const result = mergePilotDraft(
    { status: "not_started", notes: "" },
    { status: "not_started", notes: "local" },
    { status: "succeeded", notes: "" },
  );
  assert.deepEqual(result.draft, { status: "succeeded", notes: "local" });
  assert.deepEqual(result.conflicts, {});
});
test("same-field concurrent changes require a visible resolution", () => {
  const result = mergePilotDraft(
    { notes: "" },
    { notes: "local" },
    { notes: "remote" },
  );
  assert.equal(result.draft.notes, "local");
  assert.deepEqual(result.conflicts, { notes: "remote" });
});
test("a later saved value equal to the draft clears an obsolete conflict", () => {
  const result = mergePilotDraft(
    { notes: "remote" },
    { notes: "local" },
    { notes: "local" },
    { notes: "remote" },
  );
  assert.deepEqual(result.conflicts, {});
});
test("an unresolved conflict uses the newest saved value", () => {
  const result = mergePilotDraft(
    { notes: "remote" },
    { notes: "local" },
    { notes: "remote" },
    { notes: "remote" },
  );
  assert.deepEqual(result.conflicts, { notes: "remote" });
});
test("successful numeric edits do not create false concurrent conflicts", () => {
  const result = mergePilotDraft(
    { correction_minutes: null, estimated: null },
    { correction_minutes: "3", estimated: "2.5" },
    { correction_minutes: 3, estimated: 2.5 },
  );
  assert.deepEqual(result.conflicts, {});
});

test("hook retains unresolved field conflicts when another saved field changes", async () => {
  const React = await import("react");
  const { default: TestRenderer, act } = await import("react-test-renderer");
  const { usePilotBankDraft } = await import("./pilotBankDraft.js");
  let state;
  function Harness({ saved }) {
    state = usePilotBankDraft(saved);
    return null;
  }
  let renderer;
  await act(async () => {
    renderer = TestRenderer.create(
      React.createElement(Harness, {
        saved: { notes: "", status: "submitted" },
      }),
    );
  });
  await act(async () =>
    state.setDraft({ notes: "local", status: "submitted" }),
  );
  await act(async () =>
    renderer.update(
      React.createElement(Harness, {
        saved: { notes: "remote", status: "submitted" },
      }),
    ),
  );
  assert.deepEqual(state.conflicts, { notes: "remote" });
  await act(async () =>
    renderer.update(
      React.createElement(Harness, {
        saved: { notes: "remote", status: "succeeded" },
      }),
    ),
  );
  assert.deepEqual(state.conflicts, { notes: "remote" });
  assert.equal(state.draft.status, "succeeded");
  await act(async () =>
    renderer.update(
      React.createElement(Harness, {
        saved: { notes: "local", status: "succeeded" },
      }),
    ),
  );
  assert.deepEqual(state.conflicts, {});
  await act(async () => renderer.unmount());
});

test("successful evidence JSON saves compare values despite formatting and property order", () => {
  const result = mergePilotDraft(
    { rights: "{}" },
    { rights: '{"notes":"owned","scope":"private"}' },
    { rights: '{\n "scope": "private", "notes": "owned"\n}' },
  );
  assert.deepEqual(result.conflicts, {});
});

test("successful timed observations save does not conflict due to formatting", () => {
  const result = mergePilotDraft(
    { timed: "[]" },
    { timed: '[{"time_seconds":2,"note":"look away"}]' },
    { timed: '[ { "note": "look away", "time_seconds": 2 } ]' },
  );
  assert.deepEqual(result.conflicts, {});
});
