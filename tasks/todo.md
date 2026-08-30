# Selective Upstream Adoption — Executable Task List

Use with `tasks/plan.md`. Check a task only after its commit is merged and its focused verification passes. Check a checkpoint only after the merged tree passes every listed command and manual check.

## Phase 0 — Approval and Baseline

### BASE-00: Approve scope and record the clean baseline

**Description:** Confirm the two decisions in `tasks/plan.md`, then record a reproducible before-state so later failures can be attributed correctly.

**Acceptance criteria:**

- [x] Human approves the `Adopt now` scope and chooses the Klein variant policy. *Approved 2026-08-28: scope approved as listed; Klein policy is an explicit allowlist — only variants that pass the live `ST-10` gate are advertised, and supporting both 4B and 9B requires both to pass independently.*
- [x] The exact Python, Node, pnpm, OS, and Git SHA are recorded. *`tasks/baseline-2026-08-28/versions.txt` — Python 3.12.14, Node v22.21.1, pnpm 10.21.0, macOS 26.5.2 arm64, SHA `7cd3055d`.*
- [ ] The exact ComfyUI test configuration (revision, GPU, model files with hashes, launch command) is recorded in `tasks/ST-10-RUNBOOK.md` before the first live gate run. *Runbook committed with TBD fields; this criterion completes when an operator fills them in.*
- [x] Every baseline failure is captured with its command and output; no later failure is called pre-existing without this record. *Zero failures: backend 1756 passed, root 45 passed (+8 subtests), ruff clean, frontend gate clean, all three pip_audits clean. Tracked evidence: `tasks/baseline-2026-08-28/pytest-backend.txt`, `pytest-root.txt`, `ruff.txt`, `pnpm-gate.txt`, `pip_audit-*.txt`, `versions.txt`.*

**Verification:**

- [x] `git status --short`
- [x] `.venv/bin/python -m pytest backend/tests -q`
- [x] `.venv/bin/python -m pytest tests -q`
- [x] `.venv/bin/python -m ruff check backend src tests`
- [x] `cd frontend && pnpm run gate`

**Dependencies:** None; human approval required.

**Files likely touched:** None.

**Estimated scope:** S, verification only.

---

## Phase 1A — Canonical ComfyUI and Studio Contracts

### ST-01: Add a canonical multi-root ComfyUI path resolver

**Description:** Implement one resolver for default roots, `extra_model_paths.yaml`, folder aliases, root priority, model listing, safe loader-relative resolution, and the selected write root.

**Acceptance criteria:**

- [ ] `search_roots(folder_type)`, `write_root(folder_type)`, `list_models(folder_type)`, and `resolve_model_file(folder_type, ref)` use one parsed contract.
- [ ] Relative `base_path`, multiline paths, expansion, `is_default`, de-duplication, and `unet`/`diffusion_models` plus `clip`/`text_encoders` aliases are covered.
- [ ] Missing/malformed YAML degrades to configured default roots; absolute paths, `..`, and symlink escapes fail closed; cache refreshes when the config mtime changes.

**Verification:**

- [ ] `.venv/bin/python -m pytest backend/tests/test_comfy_model_paths.py -q`
- [ ] `.venv/bin/python -m ruff check backend/app/services/comfy_model_paths.py backend/tests/test_comfy_model_paths.py`

**Dependencies:** BASE-00.

**Files likely touched:**

- `backend/app/services/comfy_model_paths.py`
- `backend/tests/test_comfy_model_paths.py`
- `backend/requirements.txt` only if a direct, pinned YAML dependency is required

**Estimated scope:** M, 2–3 files.

### ST-02: Establish the five-family LoRA deployment registry

**Description:** Create one family-to-subfolder contract and make LoRA deployment writes and family reads use it.

**Acceptance criteria:**

- [ ] Registry contains exactly `zimage`, `sdxl`, `krea`, `flux`, and `flux2klein`, with unique subfolders.
- [ ] Deployment uses `write_root("loras")`; family reads consider the same subfolder under every LoRA search root.
- [ ] Missing family retains the historical Z-Image default, while an explicit unknown family is rejected and can never deploy into Z-Image.

**Verification:**

- [ ] `.venv/bin/python -m pytest backend/tests/test_family_pool_parity.py -q`
- [ ] `.venv/bin/python -m pytest backend/tests/test_training_service.py -q -k "checkpoint or deploy or import"`
- [ ] `.venv/bin/python -m ruff check backend/app/utils/training_families.py backend/app/services/lora_training.py backend/tests/test_family_pool_parity.py`

**Dependencies:** ST-01.

**Files likely touched:**

- `backend/app/utils/training_families.py`
- `backend/app/services/lora_training.py`
- `backend/tests/test_family_pool_parity.py`

**Estimated scope:** M, 3 files.

### ST-03: Route Studio LoRA discovery through the canonical resolver

**Description:** Replace the three-family dispatcher and single-root resolver with family-aware listing/resolution over all five families and all configured roots.

**Acceptance criteria:**

- [ ] Blank family maps to Z-Image; each explicit known family uses only its pool; unknown family returns `[]`.
- [ ] An extra-root Klein/FLUX LoRA is listed and architecture-inspected from the same physical file; duplicate loader-relative names prefer the highest-priority root once.
- [ ] Existing trigger matching, labels, grouping, payload shape, case-insensitive lookup, and traversal protection remain intact.

**Verification:**

- [ ] `.venv/bin/python -m pytest backend/tests/test_studio_discovery.py backend/tests/test_comfyui_utils.py -q`
- [ ] Fixture proves `flux2klein/lora_x.safetensors` is never read from the Z-Image directory.
- [ ] `.venv/bin/python -m ruff check backend/app/utils/comfyui.py backend/app/services/studio_discovery.py backend/tests/test_studio_discovery.py`

**Dependencies:** ST-01, ST-02.

**Files likely touched:**

- `backend/app/utils/comfyui.py`
- `backend/app/services/studio_discovery.py`
- `backend/tests/test_studio_discovery.py`

**Estimated scope:** M, 3 files.

### ST-04: Make Studio preflight use canonical model roots

**Description:** Resolve every workflow loader value through the shared path service instead of assuming one `models` directory.

**Acceptance criteria:**

- [ ] Checkpoint, diffusion model, VAE, text encoder, and LoRA loader classes map to the correct canonical folder types.
- [ ] Extra-root, nested, and case-different assets pass; missing assets retain actionable display paths; traversal cannot pass.
- [ ] Existing missing-node behavior and the current fail-open policy for unreachable `/object_info` do not change.

**Verification:**

- [ ] `.venv/bin/python -m pytest backend/tests/test_studio_preflight.py -q`
- [ ] `.venv/bin/python -m pytest backend/tests/test_studio_service.py -q -k preflight`
- [ ] `.venv/bin/python -m ruff check backend/app/services/lora_test_studio.py backend/tests/test_studio_preflight.py`

**Dependencies:** ST-01.

**Files likely touched:**

- `backend/app/services/lora_test_studio.py`
- `backend/tests/test_studio_preflight.py`

**Estimated scope:** S, 2 files.

### ST-05: Separate discoverable families from executable generation lanes

**Description:** Close all silent Z-Image fallbacks before Klein is offered as an executable lane.

**Acceptance criteria:**

- [ ] Discoverable/deployable families are all five; generation families initially remain `zimage`, `sdxl`, and `krea`.
- [ ] Direct requests for FLUX, pre-lane Klein, or unknown families return an error naming the requested family and enqueue nothing.
- [ ] Base-model routes, payload assembly, workflow building, and family selection can never borrow Z-Image behavior for an unsupported explicit family.

**Verification:**

- [ ] `.venv/bin/python -m pytest backend/tests/test_generation_lane_honesty.py -q`
- [ ] Tests assert every offered generation family has an on-disk workflow and unsupported requests create zero rows/jobs.
- [ ] `.venv/bin/python -m ruff check backend/app/services/studio_discovery.py backend/app/services/lora_test_studio.py backend/app/services/studio_payload.py backend/app/routes/studio.py backend/tests/test_generation_lane_honesty.py`

**Dependencies:** ST-03, ST-04.

**Files likely touched:**

- `backend/app/services/studio_discovery.py`
- `backend/app/services/lora_test_studio.py`
- `backend/app/services/studio_payload.py`
- `backend/app/routes/studio.py`
- `backend/tests/test_generation_lane_honesty.py`

**Estimated scope:** M, 5 files; exclusive Studio ownership.

### ST-06: Expose one canonical Klein model catalog

**Description:** Extend `klein_edit_helper` so listing, auto-election, explicit selection, and resolution use the same root ordering and loader-relative identifiers.

**Acceptance criteria:**

- [ ] Catalog returns readable, loader-relative Klein UNET entries from default and extra diffusion roots.
- [ ] Nested paths and duplicate basenames resolve deterministically; foreign-family and unsupported GGUF files are not auto-elected.
- [ ] 4B and 9B remain distinguishable and the catalog enforces the human-approved variant policy.

**Verification:**

- [ ] `.venv/bin/python -m pytest backend/tests/test_klein_models.py -q -k "resolve or catalog or root or nested or variant"`
- [ ] `.venv/bin/python -m ruff check backend/app/services/klein_edit_helper.py backend/tests/test_klein_models.py`

**Dependencies:** ST-01, BASE-00 variant decision.

**Files likely touched:**

- `backend/app/services/klein_edit_helper.py`
- `backend/tests/test_klein_models.py`

**Estimated scope:** S/M, 2 files.

### Checkpoint ST-A: Model discovery parity

- [ ] `.venv/bin/python -m pytest backend/tests/test_comfy_model_paths.py backend/tests/test_family_pool_parity.py backend/tests/test_studio_discovery.py backend/tests/test_comfyui_utils.py -q`
- [ ] Duplicate default/extra-root LoRA appears once and architecture inspection reads the chosen file.
- [ ] Deploy destination, picker, resolver, and preflight agree on loader-relative names.

Checkpoint ST-A is an automated merged-tree parity checkpoint only; the human resolver-contract review happens at Checkpoint 1, before any `ST-01` consumer merges.

### ST-07: Add the FLUX.2 Klein text-to-image graph and applicator

**Description:** Add an all-core-node text-to-image workflow, a dedicated settings applicator, and Klein workflow selection. Register Klein as executable only in this same commit.

**Acceptance criteria:**

- [ ] Graph has no image input and wires `UNETLoader → LoraLoaderModelOnly → ModelSamplingFlux → KSampler` with an empty FLUX.2 latent.
- [ ] Applicator overwrites every placeholder asset, validates base/LoRA whitelists, injects the trigger once, sets prompt/seed/size/steps/output, and persists effective CFG exactly as `1.0`.
- [ ] Create, comparison, preflight, workflow build, and resume take the Klein branch without any Z-Image fallback; graph node classes exist in the core ComfyUI fixture.

**Verification:**

- [ ] `.venv/bin/python -m pytest backend/tests/test_flux2_klein_studio_lane.py backend/tests/test_generation_lane_honesty.py -q`
- [ ] Tests cover traversal, missing assets, selected/automatic base, width/height wiring, model wiring, trigger de-duplication, CFG clamp, and core-node compatibility.
- [ ] `.venv/bin/python -m ruff check backend/app/services/lora_test_studio.py backend/app/services/studio_discovery.py backend/tests/test_flux2_klein_studio_lane.py`

**Dependencies:** ST-03, ST-04, ST-05, ST-06.

**Files likely touched:**

- `backend/app/services/lora_test_studio.py`
- `backend/app/services/studio_discovery.py`
- `backend/workflows/flux2_klein_t2i.json`
- `backend/tests/test_flux2_klein_studio_lane.py`

**Estimated scope:** M, 4 files; exclusive Studio ownership.

### ST-08: Expose Klein through Studio payloads and base-model routes

**Description:** Complete both single-dataset and multi-LoRA comparison entry paths using the canonical Klein catalog.

**Acceptance criteria:**

- [ ] `type=flux2klein` base-model response has the existing `{filename,label}` shape and never includes unrelated models.
- [ ] Klein payload exposes Klein checkpoints/bases, omits SDXL pass-two and misleading CFG axes, and returns a named missing-asset error before creating rows/jobs.
- [ ] Create/cancel/resume preserves family, base, prompt, seed, dimensions, steps, strength, and effective CFG for solo and comparison runs.

**Verification:**

- [ ] `.venv/bin/python -m pytest backend/tests/test_flux2_klein_studio_routes.py backend/tests/test_flux2_klein_studio_service.py -q`
- [ ] Tests cover zero/one/many bases, selected/automatic base, structured missing assets, bad base, resume, and enqueue failure.
- [ ] `.venv/bin/python -m ruff check backend/app/services/studio_payload.py backend/app/routes/studio.py backend/tests/test_flux2_klein_studio_routes.py backend/tests/test_flux2_klein_studio_service.py`

**Dependencies:** ST-07.

**Files likely touched:**

- `backend/app/services/studio_payload.py`
- `backend/app/routes/studio.py`
- `backend/tests/test_flux2_klein_studio_routes.py`
- `backend/tests/test_flux2_klein_studio_service.py`

**Estimated scope:** M, 4 files.

### ST-09: Add Klein and unsupported-family frontend behavior

**Description:** Present Klein through shared family metadata and ensure unsupported families never display another lane's controls.

**Acceptance criteria:**

- [ ] Klein has one short label, full label, and accessible badge style sourced from `trainingFamilies.js`.
- [ ] Selecting Klein requests `type=flux2klein`, requires a valid comparison base, and shows none of the Krea-, SDXL-, or Z-Image-only settings.
- [ ] Direct FLUX/unsupported state displays the named backend refusal and no Z-Image controls.

**Verification:**

- [ ] `cd frontend && pnpm exec node --test --test-concurrency=1 src/utils/trainingFamilies.test.js`
- [ ] `cd frontend && pnpm run lint && pnpm run typecheck && pnpm run build && pnpm run check:bundle`
- [ ] Manual keyboard/high-contrast checks for family picker, empty model state, and family lock.

**Dependencies:** ST-05 contract, ST-08 for final verification.

**Files likely touched:**

- `frontend/src/utils/trainingFamilies.js`
- `frontend/src/utils/trainingFamilies.test.js`
- `frontend/src/components/dataset/studio/LoraPicker.jsx`
- `frontend/src/components/dataset/studio/LegacyDatasetStudio.jsx`
- generated `frontend/dist/**` by integration owner

**Estimated scope:** M, 4 source/test files plus generated output.

### ST-10: Prove the Klein lane across service boundaries and real ComfyUI

**Description:** Add one cross-path regression and execute the live GPU acceptance gate.

**Acceptance criteria:**

- [ ] Extra-root Klein LoRA/base travel through picker, architecture resolution, payload, preflight, graph build, and captured queue job unchanged.
- [ ] Solo and comparison paths create durable cells; unsupported FLUX, missing assets, and invalid bases create zero queued jobs and zero successful rows.
- [ ] Live fixed-seed strength 0/1 run completes, differs as expected, resumes faithfully, works from an extra root, and validates every claimed Klein variant.

**Verification:**

- [ ] `.venv/bin/python -m pytest backend/tests/test_flux2_klein_studio_integration.py backend/tests/test_studio_routes.py backend/tests/test_studio_service.py -q`
- [ ] Live run checks graph, filenames, effective CFG, ComfyUI errors, cancel/resume, and 4B/9B policy.

**Dependencies:** ST-08, ST-09.

**Files likely touched:**

- `backend/tests/test_flux2_klein_studio_integration.py`

**Estimated scope:** S code plus external verification.

---

## Phase 1B — Caption Authorship and Protection

### CA-01: Add the persisted caption-origin contract

**Description:** Add a nullable image column and additive migration without inventing attribution for legacy rows.

**Acceptance criteria:**

- [ ] Fresh and historical databases contain nullable `caption_origin VARCHAR(16)` after startup.
- [ ] Legacy captions remain byte-identical with `caption_origin IS NULL`; readiness reports the new migration version.
- [ ] Migration is additive, retry-safe, backed up by existing migration safeguards, and never renumbered after publication.

**Verification:**

- [ ] `.venv/bin/python -m pytest backend/tests/test_smoke.py -q`
- [ ] Historical schema fixture proves old caption/origin values.
- [ ] `.venv/bin/python -m ruff check backend/app/__init__.py backend/app/models.py backend/tests/test_smoke.py`

**Dependencies:** BASE-00; assign migration number at merge time.

**Files likely touched:**

- `backend/app/models.py`
- `backend/app/__init__.py`
- `backend/tests/test_smoke.py`

**Estimated scope:** S, 3 files.

### CA-02: Centralize caption text, origin, and provenance writes

**Description:** Add a domain helper for atomic caption metadata and SQL protection predicates.

**Acceptance criteria:**

- [ ] Blank text clears origin/provenance; human text becomes `asserted`; model text is stamped with the actual `joycaption` or `ollama` engine.
- [ ] Unknown engine is `NULL`, not false attribution; Ollama cannot inherit stale JoyCaption provenance.
- [ ] `unprotected_clause` explicitly includes SQL `NULL` and selects blank, machine, and unknown rows but excludes non-empty asserted rows.

**Verification:**

- [ ] `.venv/bin/python -m pytest backend/tests/test_caption_origin.py -q`
- [ ] Tests cover empty, asserted, each engine, unknown, and SQL three-valued logic.
- [ ] `.venv/bin/python -m ruff check backend/app/services/caption_origin.py backend/tests/test_caption_origin.py`

**Dependencies:** CA-01.

**Files likely touched:**

- `backend/app/services/caption_origin.py`
- `backend/tests/test_caption_origin.py`

**Estimated scope:** S, 2 files.

### CA-03: Make human, clear, copy, backup, and undo paths preserve the tuple

**Description:** Extract manual save, find/replace, clear-caption, and atomic caption-tuple application into the focused caption module (`caption_origin.py` or a `caption_service.py`); `face_dataset_service.py` may retain thin compatibility delegates. Backup/restore orchestration stays with its existing transactional owner and undo/history stays with `curation_history.py`; those owners call the shared tuple operation. Preserve the complete metadata tuple across lifecycle operations.

**Acceptance criteria:**

- [ ] Caption-specific mutation logic (manual save, find/replace, clear, atomic tuple application) lives in the focused caption module; `face_dataset_service.py` gains no new caption-mutation bodies beyond thin delegates.
- [ ] Manual save, find/replace, and user-supplied sidecars stamp `asserted`; clear/regenerate clears all metadata.
- [ ] Reconstruction/copy/backup/restore preserve unchanged caption origin/provenance; legacy backup format still restores.
- [ ] Curation history snapshots and undo restore text, origin, and provenance atomically.

**Verification:**

- [ ] `.venv/bin/python -m pytest backend/tests/test_curation_history.py backend/tests/test_dataset_service.py backend/tests/test_dataset_routes.py -q`
- [ ] Tests include asserted and machine backup round trips plus undo from manual back to machine caption.
- [ ] `.venv/bin/python -m ruff check backend/app/services/face_dataset_service.py backend/app/services/curation_history.py backend/tests/test_curation_history.py backend/tests/test_dataset_service.py backend/tests/test_dataset_routes.py`

**Dependencies:** CA-02.

**Files likely touched:**

- `backend/app/services/caption_origin.py` (or a focused `caption_service.py`)
- `backend/app/services/face_dataset_service.py`
- `backend/app/services/curation_history.py`
- `backend/tests/test_curation_history.py`
- `backend/tests/test_dataset_service.py`
- `backend/tests/test_dataset_routes.py`

**Estimated scope:** M, 5 files; exclusive caption backend ownership.

### CA-04: Protect manual captions in every inference lane

**Description:** Make forced batch semantics truthful and add a pre-write concurrency guard.

**Acceptance criteria:**

- [ ] Unforced processes blanks; forced processes machine/legacy-unknown but skips asserted; `include_asserted: true` is the only explicit override.
- [ ] Character, concept, and style lanes share the rule, and progress totals count only admitted rows.
- [ ] Before persisting, the row is reloaded and compared with its planned tuple; changed, cleared, or deleted rows are skipped, so a mid-run manual action wins.
- [ ] Guarded inference persistence uses the same focused caption module introduced in CA-03.

**Verification:**

- [ ] `.venv/bin/python -m pytest backend/tests/test_caption_asserted_protection.py backend/tests/test_captioning.py backend/tests/test_joycaption_provenance.py backend/tests/test_concept_caption_omission.py backend/tests/test_concept_leak_detection.py -q`
- [ ] Concurrency test mutates/clears/deletes inside mocked inference and proves no resurrection/overwrite.
- [ ] `.venv/bin/python -m ruff check backend/app/services/face_dataset_service.py backend/app/routes/datasets.py backend/tests/test_caption_asserted_protection.py`

**Dependencies:** CA-02, CA-03.

**Files likely touched:**

- `backend/app/services/face_dataset_service.py`
- `backend/app/routes/datasets.py`
- `backend/tests/test_caption_asserted_protection.py`
- `backend/tests/test_joycaption_provenance.py`
- `backend/tests/test_concept_caption_omission.py`

**Estimated scope:** M, 5 files; same agent as CA-03, sequential.

### CA-05: Expose caption origin in every dataset image payload

**Description:** Add coarse authorship to full and cursor-paginated responses without exposing raw provenance unnecessarily.

**Acceptance criteria:**

- [ ] All image payload paths include additive `caption_origin`; legacy rows serialize `null`.
- [ ] Full and paginated representations agree and no filesystem/model-secret data is added.
- [ ] Existing clients that ignore the field remain compatible.

**Verification:**

- [ ] `.venv/bin/python -m pytest backend/tests/test_dataset_routes.py -q`
- [ ] `.venv/bin/python -m ruff check backend/app/services/face_dataset_service.py backend/tests/test_dataset_routes.py`

**Dependencies:** CA-01.

**Files likely touched:**

- `backend/app/services/face_dataset_service.py`
- `backend/tests/test_dataset_routes.py`

**Estimated scope:** S, 2 files.

### CA-06: Add pure frontend caption-origin semantics

**Description:** Centralize labels, tooltips, asserted checks, and safe handling of legacy/future origin values.

**Acceptance criteria:**

- [ ] `asserted`, JoyCaption, Ollama, unrecorded, and unknown future values have honest stable labels.
- [ ] `NULL` is never called machine-generated; unknown non-empty values remain visible; empty captions display no author.
- [ ] Pure helpers can compute rewrite/spare counts without JSX.

**Verification:**

- [ ] `cd frontend && pnpm exec node --test src/utils/captionOrigin.test.js`
- [ ] `cd frontend && pnpm run lint && pnpm run typecheck`

**Dependencies:** CA-05 API contract.

**Files likely touched:**

- `frontend/src/utils/captionOrigin.js`
- `frontend/src/utils/captionOrigin.test.js`

**Estimated scope:** S, 2 files.

### CA-07: Display authorship where captions are read and edited

**Description:** Add accessible attribution to the tile and expanded editor while distinguishing saved text from an unsaved draft.

**Acceptance criteria:**

- [ ] Known author badge appears beside non-empty saved captions; expanded editor explains legacy/unknown origin honestly.
- [ ] Once draft text differs, old attribution is replaced by an “unsaved edit” state explaining that save records it as the user's caption.
- [ ] Meaning is not icon-only; accessible text/tooltips and keyboard behavior pass.

**Verification:**

- [ ] Focused component tests for saved/unsaved/legacy states.
- [ ] `cd frontend && pnpm run lint && pnpm run typecheck && pnpm run test`

**Dependencies:** CA-06.

**Files likely touched:**

- `frontend/src/components/dataset/DatasetGridItem.jsx`
- `frontend/src/components/dataset/CaptionEditorDialog.jsx`
- one focused component or contract test

**Estimated scope:** M, 3 files.

### CA-08: Make Re-caption UI match the protected server scope

**Description:** Show exact rewrite/spare counts and make replacing asserted captions an explicit unchecked action.

**Acceptance criteria:**

- [ ] Default confirmation names machine, asserted, and author-unrecorded counts and matches server-admitted rows.
- [ ] Ordinary Re-caption is disabled if every existing caption is asserted.
- [ ] “Also replace captions I wrote” appears only when relevant, defaults false every time, and sends `include_asserted` only after a second explicit destructive confirmation.

**Verification:**

- [ ] Focused pure count/confirmation tests.
- [ ] `cd frontend && pnpm run gate`
- [ ] Manual default, override, and all-asserted flows.

**Dependencies:** CA-04, CA-06, CA-07.

**Files likely touched:**

- `frontend/src/components/dataset/DatasetWorkspace.jsx`
- `frontend/src/components/dataset/captionCategory.js`
- corresponding test
- `frontend/src/hooks/useDataset.js`
- generated `frontend/dist/**` by integration owner

**Estimated scope:** M, 4 source/test files plus generated output.

### Checkpoint CA: Caption contract complete

- [ ] `.venv/bin/python -m pytest backend/tests/test_smoke.py backend/tests/test_caption_origin.py backend/tests/test_caption_asserted_protection.py backend/tests/test_captioning.py backend/tests/test_joycaption_provenance.py backend/tests/test_concept_caption_omission.py backend/tests/test_curation_history.py backend/tests/test_dataset_routes.py -q`
- [ ] `.venv/bin/python -m ruff check backend`
- [ ] `cd frontend && pnpm run gate`
- [ ] Manual batch, override, mid-flight edit, backup/restore, and undo protocol from `tasks/plan.md` passes.

---

## Phase 1C — Bokeh-aware Sharpness

### QS-01: Pin sharpness behavior with deterministic synthetic fixtures

**Description:** Generate bokeh, uniform-blur, artifact-speck, small-image, and ordinary-sharp images in memory and assert category semantics.

**Acceptance criteria:**

- [ ] Current whole-frame algorithm's bokeh failure is reproducible before the behavior change.
- [ ] Target contract requires bokeh above the accepted boundary, uniform blur and artifact speck below low-sharpness, integer 0–100, and deterministic repeats.
- [ ] Fixtures do not depend on external files, random state, OpenCV, GPU, or timing.

**Verification:**

- [ ] `.venv/bin/python -m pytest backend/tests/test_import_analysis.py -q`
- [ ] `.venv/bin/python -m ruff check backend/tests/test_import_analysis.py`

**Dependencies:** BASE-00.

**Files likely touched:**

- `backend/tests/test_import_analysis.py`

**Estimated scope:** S, 1 file.

### QS-02: Implement tiled p90 Laplacian scoring and version 2

**Description:** Compute clamp-safe Laplacian responses once, derive per-tile variance, use p90 rather than maximum, preserve the 0–100 public scale, and bump the analysis version.

**Acceptance criteria:**

- [ ] At most 8×8 tiles, no tile below 32 px, outer unfiltered border excluded, both convolutions run once per image, nearest-rank p90 selected.
- [ ] Bokeh passes while uniform blur and one speck remain low; result shape, 0–100 range, and reason vocabulary remain compatible. Score-mapping and admission constants are recalibrated and documented using a small, rights-cleared real-image reference corpus, including before/after green, amber, red, low-sharpness, and accepted counts. *The tracked placeholder corpus lives at `tasks/reference-corpus/` (deterministic generator included; `data/reference-corpus/` is the gitignored runtime copy). Constants calibrated only against placeholders are PROVISIONAL and must not be merged as release-ready: final constants require real, rights-cleared photographs, an explicit operator gate before Checkpoint QS sign-off. Never download images.*
- [ ] New analysis stores version 2; v1 JSON remains readable and is never rewritten by GET/startup; explicit v2 refresh preserves existing face-analysis and coverage metadata.
- [ ] Full and cursor-paginated dataset image responses expose `analysis.analysis_version == 2`, proven in `backend/tests/test_dataset_routes.py`; missing analysis remains distinguishable by the absence of that nested version.

**Verification:**

- [ ] `.venv/bin/python -m pytest backend/tests/test_import_analysis.py backend/tests/test_dataset_service.py backend/tests/test_dataset_routes.py backend/tests/test_image_improve.py -q`
- [ ] Optional non-gating 4K micro-benchmark documents bounded thumbnail work.
- [ ] `.venv/bin/python -m ruff check backend/app/services/import_analysis.py backend/tests/test_import_analysis.py backend/tests/test_dataset_routes.py`

**Dependencies:** QS-01.

**Files likely touched:**

- `backend/app/services/import_analysis.py`
- `backend/tests/test_import_analysis.py`

**Estimated scope:** M, 2 files.

### QS-03: Keep the standalone prototype in exact scoring parity

**Description:** Port the same algorithm/constants to `avatar_prep` and assert exact equality on the shared synthetic contract.

**Acceptance criteria:**

- [ ] Backend and prototype return identical scores and threshold-derived outcomes for every fixture.
- [ ] Duplication is explicitly documented as a packaging/runtime boundary; constants cannot drift unnoticed because parity is tested.
- [ ] Prototype manifest compatibility is preserved unless an existing version field specifically requires an additive update.

**Verification:**

- [ ] `.venv/bin/python -m pytest backend/tests/test_import_analysis.py tests/test_core.py -q`
- [ ] `.venv/bin/python -m ruff check backend src tests`

**Dependencies:** QS-02.

**Files likely touched:**

- `src/avatar_prep/core.py`
- `tests/test_core.py`
- `backend/tests/test_import_analysis.py`

**Estimated scope:** S, 3 files.

### QS-04: Surface stale technical analysis and explicit refresh semantics

**Description:** Distinguish missing, v1/outdated, and v2/current analysis in the Corpus Workbench and explain the existing refresh action.

**Acceptance criteria:**

- [ ] Missing is “not analyzed,” v1 is “outdated,” v2+ is current; no automatic network/CPU work occurs on render or GET.
- [ ] Outdated count and refresh tooltip explain that refresh applies bokeh-aware scoring.
- [ ] Refresh preserves unrelated face/coverage metadata and the user guide documents explicit upgrade behavior.

**Verification:**

- [ ] `cd frontend && pnpm exec node --test src/utils/technicalAnalysis.test.js`
- [ ] `cd frontend && pnpm run gate`
- [ ] Manual v1 dataset refresh clears notice without losing face/coverage data.

**Dependencies:** QS-02.

**Files likely touched:**

- `frontend/src/utils/technicalAnalysis.js`
- `frontend/src/utils/technicalAnalysis.test.js`
- `frontend/src/components/dataset/CorpusWorkbench.jsx`
- `docs/DATASET_GUIDE.md`
- generated `frontend/dist/**` by integration owner

**Estimated scope:** M, 4 source/docs files plus generated output.

### Checkpoint QS: Technical analysis complete

- [ ] `.venv/bin/python -m pytest backend/tests/test_import_analysis.py backend/tests/test_dataset_service.py backend/tests/test_image_improve.py tests/test_core.py -q`
- [ ] `.venv/bin/python -m ruff check backend src tests`
- [ ] `cd frontend && pnpm run gate`
- [ ] Manual bokeh/blur/speck and v1 refresh protocol passes.

---

## Phase 1D — Stale Frontend Chunk Recovery

### LZ-01: Add a testable one-shot lazy page loader

**Description:** Wrap dynamic page imports so the first failed import reloads once and a repeated/current failure reaches the existing error boundary.

**Acceptance criteria:**

- [ ] Successful import returns the module and clears the session guard.
- [ ] First rejection sets the guard and reloads exactly once; second rejection rethrows the original error.
- [ ] Unavailable/denied storage surfaces the error rather than risking a reload loop; no successful import reloads.

**Verification:**

- [ ] `cd frontend && pnpm exec node --test src/utils/lazyPage.test.js`
- [ ] `cd frontend && pnpm run lint && pnpm run typecheck`

**Dependencies:** BASE-00.

**Files likely touched:**

- `frontend/src/utils/lazyPage.js`
- `frontend/src/utils/lazyPage.test.js`

**Estimated scope:** S, 2 files.

### LZ-02: Route all page imports through lazy recovery

**Description:** Replace the six direct page `lazy()` declarations without moving Suspense or pulling pages into the entry bundle.

**Acceptance criteria:**

- [ ] Dataset, Studio, Settings, Setup, Guide, and Runs all use the wrapper; shell/navigation remain mounted during loading.
- [ ] Production build remains split and within bundle budget.
- [ ] Build-A/open-tab to build-B navigation reloads once and succeeds; a missing build-B chunk stops after one reload and shows the normal error state.

**Verification:**

- [ ] `cd frontend && pnpm run gate`
- [ ] Manual stale-build and genuinely-missing-chunk protocols pass.

**Dependencies:** LZ-01.

**Files likely touched:**

- `frontend/src/App.jsx`
- one narrow route-loading contract test
- generated `frontend/dist/**` by integration owner

**Estimated scope:** S, 2 source/test files plus generated output.

---

## Checkpoint CORE — Required adoption release

- [ ] All ST, CA, QS, and LZ task checkboxes are complete.
- [ ] `.venv/bin/python -m pytest backend/tests -q`
- [ ] `.venv/bin/python -m pytest tests -q`
- [ ] `.venv/bin/python -m ruff check backend src tests`
- [ ] All three `pip_audit` commands in `tasks/plan.md` pass.
- [ ] `cd frontend && pnpm run gate && pnpm audit --prod --audit-level high && pnpm run e2e`
- [ ] Real ComfyUI Klein protocol passes for every advertised variant.
- [ ] `git status --short` shows no unintended output.
- [ ] Human reviews behavior and approves the core release.

---

## Phase 2 — Corpus Workbench UX

### CW-01: Extract the corpus query-state model

**Description:** Move filter/search/sort/normalization logic into a pure utility before growing the component.

**Acceptance criteria:**

- [ ] Existing six filters retain membership semantics; search matches source name, filename, and numeric ID case-insensitively, not captions.
- [ ] Deterministic sorts include newest/import order, oldest, source name, and needs-attention with stable ID tie-breaks.
- [ ] Invalid persisted values normalize to documented defaults and input arrays are never mutated.

**Verification:**

- [ ] `cd frontend && pnpm exec node --test src/utils/corpusWorkbenchState.test.js`
- [ ] `cd frontend && pnpm run lint && pnpm run typecheck`

**Dependencies:** CORE checkpoint.

**Files likely touched:**

- `frontend/src/utils/corpusWorkbenchState.js`
- `frontend/src/utils/corpusWorkbenchState.test.js`

**Estimated scope:** S, 2 files.

### CW-02: Add accessible search, sort, and honest empty states

**Description:** Wire query state into the workbench while preserving batch-action scope and deterministic selection.

**Acceptance criteria:**

- [ ] Search/sort compose with filters; showing N/M is final output; filtered-empty explains controls and offers reset.
- [ ] Hidden selection moves to the first visible row or clears; batch counts/actions still operate on their intended full corpus.
- [ ] Search is labeled, filters retain `aria-pressed`, sort is keyboard-operable, and existing detail behavior remains stable.

**Verification:**

- [ ] `cd frontend && pnpm exec node --test src/utils/corpusWorkbenchState.test.js src/components/dataset/CorpusWorkbench.test.js`
- [ ] `cd frontend && pnpm run lint && pnpm run typecheck`

**Dependencies:** CW-01.

**Files likely touched:**

- `frontend/src/components/dataset/CorpusWorkbench.jsx`
- `frontend/src/components/dataset/CorpusWorkbench.test.js`
- `frontend/src/utils/corpusWorkbenchState.js`

**Estimated scope:** M, 3 files.

### CW-03: Persist review position per dataset

**Description:** Save validated query/filter/sort/selection state under a dataset-scoped key and recover safely from stale or denied storage.

**Acceptance criteria:**

- [ ] Dataset A state never leaks to B; existing selected image restores; removed/hidden image falls back safely.
- [ ] Corrupt/stale/denied storage returns defaults; reset clears controls without deleting dataset data.
- [ ] Persistence stores only UI state, never image content, captions, rights, or other private metadata.

**Verification:**

- [ ] `cd frontend && pnpm exec node --test src/utils/corpusWorkbenchState.test.js src/components/dataset/CorpusWorkbench.test.js src/hooks/usePersistedPreference.test.js`
- [ ] `cd frontend && pnpm run gate && pnpm run e2e`
- [ ] Manual two-dataset, keyboard, corrupt-storage, and 200-image checks pass.

**Dependencies:** CW-02.

**Files likely touched:**

- `frontend/src/components/dataset/CorpusWorkbench.jsx`
- `frontend/src/utils/corpusWorkbenchState.js`
- their tests
- `frontend/src/hooks/usePersistedPreference.js` only if a reusable codec is required
- generated `frontend/dist/**` by integration owner

**Estimated scope:** M, 3–5 source/test files plus generated output.

### Checkpoint CW: Corpus UX complete

- [ ] Focused CW tests pass.
- [ ] `cd frontend && pnpm run gate && pnpm run e2e`
- [ ] Two-dataset isolation, stale selection, keyboard flow, and large-corpus smoke pass.
- [ ] Lightweight release proof: `git diff --exit-code <CORE_RELEASE_SHA>..HEAD -- backend src tests pyproject.toml` is empty. If non-empty, the Corpus batch loses lightweight status and the affected CORE checks are selected according to the changed files; if empty, the CORE backend pytest, Ruff, and `pip_audit` gates are not rerun.

---

## Optional Epic A — Fork-native Gallery

### GA-00: Approve the Gallery source and mutation contract

**Description:** Freeze eligible rows, IDs, cursor order, filters, liked semantics, ZIP bounds, and whether deletion ships.

**Acceptance criteria:**

- [ ] Human approves dataset generated rows plus completed Studio rows, source-qualified IDs, stable cursor tuple, and no invented dataset “like” field.
- [ ] Missing/empty selection never means “all”; ZIP count/byte limits are selected.
- [ ] Delete is explicitly approved or excluded; Studio restore and reconstruction-pair semantics are written down.

**Verification:** Human review of the contract.

**Dependencies:** CORE checkpoint.

**Files likely touched:** decision record only.

**Estimated scope:** XS.

### GA-01: Build the read-only Gallery query API

**Description:** Aggregate eligible generated dataset images and completed Studio cells behind one read-only, cursor-paginated API without introducing upstream Bank or Canvas entities.

**Acceptance criteria:**

- [ ] Newest-first opaque cursor over `(created_at, source_type, row_id)` does not duplicate/skip under concurrent inserts.
- [ ] Dataset/kind/liked filters and counts are honest across eligible, file-backed, non-trashed rows.
- [ ] JSON uses source-qualified IDs and safe URLs; internal paths never appear; invalid query values return stable 400s.

**Verification:** `.venv/bin/python -m pytest backend/tests/test_app_gallery.py backend/tests/test_dataset_routes.py backend/tests/test_studio_routes.py -q`

**Dependencies:** GA-00.

**Files likely touched:** `backend/app/services/app_gallery.py`, `backend/app/routes/gallery.py`, route registration, `backend/tests/test_app_gallery.py`.

**Estimated scope:** M, 4 files.

### GA-02: Add safe media serving and bounded selection ZIP

**Description:** Resolve source-qualified Gallery IDs through existing ownership/containment boundaries and download only an explicitly bounded selection.

**Acceptance criteria:**

- [ ] Source-qualified lookup revalidates ownership/status/file presence and uses contained-file serving.
- [ ] ZIP accepts a bounded explicit list only, uses collision-safe names and spooled/streamed output, and enforces aggregate byte limits.
- [ ] Traversal, symlink escape, stale IDs, mixed source rows, and duplicate filenames are tested.

**Verification:** `.venv/bin/python -m pytest backend/tests/test_app_gallery.py backend/tests/test_dataset_routes.py backend/tests/test_studio_routes.py -q`

**Dependencies:** GA-01.

**Files likely touched:** `backend/app/routes/gallery.py`, `backend/app/services/gallery_download.py`, `backend/tests/test_app_gallery.py`, optional existing contained-file helper.

**Estimated scope:** M, 3–4 files.

### GA-03: Add recoverable Gallery deletion

**Description:** Add deletion only if every included source type has coherent recoverable behavior and protected reconstruction/active-job invariants remain intact.

**Acceptance criteria:**

- [ ] Non-empty explicit IDs are revalidated immediately; active Studio cells and unresolved reconstruction pairs are skipped safely.
- [ ] Dataset rows reuse recoverable deletion; Studio deletion has coherent restore or remains disabled.
- [ ] Response separates deleted/skipped/missing/conflicting IDs; partial failures cannot desynchronize DB/files.

**Verification:** `.venv/bin/python -m pytest backend/tests/test_app_gallery.py backend/tests/test_trash.py backend/tests/test_image_improve.py backend/tests/test_studio_service.py -q`

**Dependencies:** GA-01, preferably GA-02, explicit deletion approval.

**Files likely touched:** `backend/app/services/app_gallery.py`, `backend/app/routes/gallery.py`, `backend/tests/test_app_gallery.py`, optional trash service.

**Estimated scope:** M, 3–4 files.

### GA-04: Build pure Gallery frontend state

**Description:** Define URL, pagination, request-generation, de-duplication, empty-state, and selection rules outside React before building the page.

**Acceptance criteria:**

- [ ] URL/cursor/filter construction is exact; page merges de-duplicate qualified IDs.
- [ ] Filter changes invalidate old requests, and late responses cannot append to the new feed.
- [ ] Empty/filtered-empty messages and selection pruning are deterministic.

**Verification:** `cd frontend && pnpm exec node --test src/utils/appGallery.test.js && pnpm run lint && pnpm run typecheck`

**Dependencies:** GA-01 API contract.

**Files likely touched:** `frontend/src/utils/appGallery.js`, `frontend/src/utils/appGallery.test.js`.

**Estimated scope:** S, 2 files.

### GA-05: Add responsive Gallery browsing and lightbox

**Description:** Build a read-oriented page and accessible lightbox over the approved Gallery API without duplicating dataset curation controls.

**Acceptance criteria:**

- [ ] Responsive lazy grid, filters, stable load-more, and truthful metadata work without duplicating curation controls.
- [ ] Lightbox supports previous/next, arrow keys, Escape, focus trap, body-scroll lock, and accessible controls.
- [ ] Network, empty, filtered-empty, and partial states differ clearly.

**Verification:** Focused Gallery tests, then `cd frontend && pnpm run lint && pnpm run typecheck`.

**Dependencies:** GA-01, GA-02, GA-04.

**Files likely touched:** page, grid, lightbox, one focused test. Split controller/lightbox if more than 5 files.

**Estimated scope:** Two M tasks if needed.

### GA-06: Add route/navigation, ZIP, and gated deletion UI

**Description:** Integrate Gallery into the lazy-loaded shell, expose explicit-selection downloads, and show deletion only when the backend mutation contract was separately approved.

**Acceptance criteria:**

- [ ] Gallery route uses `lazyPage`; desktop/mobile navigation agree; bundle budget passes.
- [ ] ZIP is disabled for empty selection and sends explicit IDs.
- [ ] Delete names exact count, retains failed/skipped selection, and removes only server-confirmed deletions.

**Verification:** `cd frontend && pnpm run gate && pnpm run e2e` plus mobile/keyboard manual pass.

**Dependencies:** LZ-02, GA-02, GA-05, and GA-03 only if delete ships.

**Files likely touched:** `frontend/src/App.jsx`, Gallery page/toolbar/tests, generated dist.

**Estimated scope:** M, 4–5 source/test files plus output.

### Checkpoint GA: Gallery release gate

- [ ] Read-only API, cursor-under-insert, mixed-source ZIP, containment, and selection-limit tests pass.
- [ ] If deletion ships, restore/reconstruction/active-job tests and explicit human approval pass; otherwise no delete control or route is exposed.
- [ ] `.venv/bin/python -m pytest backend/tests/test_app_gallery.py backend/tests/test_dataset_routes.py backend/tests/test_studio_routes.py -q`
- [ ] `cd frontend && pnpm run gate && pnpm run e2e`
- [ ] Mobile, keyboard, lightbox focus, stale cursor, and partial-error manual checks pass.

---

## Optional Epic B — SeedVR2 Improvement

### SV-00: Complete dependency, license, download, and real-GPU spike

**Description:** Prove the current external node/weight contract and one real whole-frame render before creating any shipping configuration or UI.

**Acceptance criteria:**

- [ ] Exact node-pack revisions/classes, weight URLs/hashes/licenses/sizes, ComfyUI compatibility, and Python dependencies are recorded.
- [ ] User approves approximately 3.9 GB of downloads; nothing is silently installed into user-owned ComfyUI.
- [ ] A non-sensitive whole-frame render records dimensions, color behavior, runtime, and peak VRAM; without it the epic remains experimental/blocked.

**Verification:** Redacted evidence and human review.

**Dependencies:** CORE checkpoint and explicit external authorization.

**Files likely touched:** decision/spike record only.

**Estimated scope:** M research/external.

### SV-01: Add SeedVR2 config and capability contracts

**Description:** Add validated additive settings and a network-free capability state machine that reports exactly what is missing.

**Acceptance criteria:** defaults/ranges are additive; capability distinguishes missing/invalid weights, nodes, ComfyUI, and ready; probe is network-free; Klein stays unchanged.

**Verification:** `.venv/bin/python -m pytest backend/tests/test_config.py backend/tests/test_capabilities.py -q`

**Dependencies:** SV-00.

**Files likely touched:** `backend/app/config.py`, `backend/app/capabilities.py`, their tests.

**Estimated scope:** M, 4 files.

### SV-02: Add contained asset resolution and pure graph construction

**Description:** Resolve only approved on-disk assets and build a deterministic, fixture-tested ComfyUI graph with no import-time network behavior.

**Acceptance criteria:** configured on-disk weights only; typed failures; live/fixture node names; pure graph pins links/settings/offload; no network; contained paths.

**Verification:** `.venv/bin/python -m pytest backend/tests/test_seedvr2_assets.py backend/tests/test_seedvr2_graph.py backend/tests/test_comfyui_object_info_contract.py -q`

**Dependencies:** SV-01.

**Files likely touched:** two new services and two tests; split assets and graph into separate commits if needed.

**Estimated scope:** Two S/M tasks.

### SV-03: Dispatch image improvement by explicit engine

**Description:** Extend the existing image-improvement boundary with a named engine while preserving its pair, queue, rollback, and idempotency contracts.

**Acceptance criteria:** explicit `klein|seedvr2`; absent remains Klein; unavailable fails before mutation; no fallback; queue/capacity/pair/idempotency behavior stays equal; actual engine/provenance persists.

**Verification:** `.venv/bin/python -m pytest backend/tests/test_image_improve.py backend/tests/test_seedvr2.py -q`

**Dependencies:** SV-02.

**Files likely touched:** face service, dataset route, two tests.

**Estimated scope:** M, 4 files.

### SV-04: Prove completion, provenance, restart, and QA parity

**Description:** Make SeedVR2 completion as durable and diagnosable as existing Klein completion, including post-output technical and identity comparison.

**Acceptance criteria:** exact job-output linking; normalized/hashed output and provenance; technical/identity comparison; replay idempotency; failure restores prior state.

**Verification:** `.venv/bin/python -m pytest backend/tests/test_seedvr2.py backend/tests/test_image_improve.py backend/tests/test_infer_workers.py backend/tests/test_worker_startup.py -q`

**Dependencies:** SV-03.

**Files likely touched:** helper, face service, two tests.

**Estimated scope:** M, 4 files.

### SV-05: Add explicit weight setup without node auto-install

**Description:** Offer deliberate, verified model-weight installation while leaving third-party node-pack installation under the user's control.

**Acceptance criteria:** size/destination/free-space shown; explicit click; pinned URLs/hashes; temp/atomic/resume/cancel; token requirement; node pack remains manual; readiness validates files/classes.

**Verification:** backend setup tests and focused frontend setup test, then `pnpm run gate`.

**Dependencies:** SV-01, SV-02, download approval.

**Files likely touched:** split into one backend M task and one frontend M task, each ≤5 files.

**Estimated scope:** Two M tasks.

### SV-06: Add honest improvement-engine UI

**Description:** Let the user choose between generative reconstruction and detail restoration with capability-aware, non-fallback behavior.

**Acceptance criteria:** Klein is generative reconstruction, SeedVR2 detail restoration; unavailable reasons are exact; requests name engine; review is engine-neutral; batch never silently uses a default.

**Verification:** focused engine/lightbox tests and `cd frontend && pnpm run gate`.

**Dependencies:** SV-03, SV-05 capability contract.

**Files likely touched:** pure engine utility/test, lightbox, review, dataset hook. Split bulk control follow-up if >5 files.

**Estimated scope:** M, 5 files.

### SV-07: Add automatic high-resolution tiling

**Description:** Add a separately tested tiled graph only after the whole-frame lane is proven, with a pure tile plan and explicit dependency state.

**Acceptance criteria:** pure tile plan; conservative activation threshold; node validation; honest no-tiling behavior; overlap/blending/VAE/offload/odd-size tests; no incompatible/GPL arithmetic-only node pack.

**Verification:** SeedVR2 tiling backend/frontend tests and gates.

**Dependencies:** SV-00 through SV-06 and successful whole-frame live render.

**Files likely touched:** helper/test plus setup utility/test/card, split backend/frontend.

**Estimated scope:** Two M tasks.

### SV-08: Pass the real hardware release matrix

**Description:** Validate advertised whole-frame and tiled support on the actual GPU classes and failure/restart conditions named by the release.

**Acceptance criteria:** whole/tiled renders on 12 GB-class and higher-VRAM GPUs; dimensions, seams, color, identity, sharpness, time, peak VRAM; missing-assets/nodes, restart, cancellation, and replay tested; unverified lanes remain gated.

**Verification:** signed-off redacted hardware matrix.

**Dependencies:** SV-07.

**Files likely touched:** verification record only.

**Estimated scope:** External gate.

### Checkpoint SV: SeedVR2 release gate

- [ ] Whole-frame implementation, setup, and UI automated suites pass before any tiling work begins.
- [ ] Tiling remains disabled until its node contract and two-class hardware matrix pass.
- [ ] No unapproved download, node installation, network probe, or silent Klein fallback exists.
- [ ] Full backend/frontend gates pass and the feature remains capability-gated for unverified hardware/configurations.

---

## Optional Epic C — OpenRouter Generation

### OR-00: Verify the current provider contract with official docs and one live request

**Description:** Establish the live API, model, billing, privacy, and error contract with synthetic data before relying on upstream mocks.

**Acceptance criteria:** endpoint/auth/reference/size/response/model/error/rate-limit limits confirmed; chosen model supports reference images; redacted fixture; actual cost and retention/privacy reviewed; no credential means BLOCKED.

**Verification:** authorized low-cost request with synthetic input and human review.

**Dependencies:** CORE checkpoint and explicit key/spend/data authorization.

**Files likely touched:** spike record only.

**Estimated scope:** M research/external.

### OR-01: Implement the isolated provider adapter

**Description:** Encapsulate authenticated request/response handling and typed, sanitized errors without touching the broader generation pipeline.

**Acceptance criteria:** engine contract returns bytes or typed refusal; key only in auth header; distinct timeout/auth/credit/model/rate/server/malformed errors; bounded sanitized details; all refs or refusal; no fallback; no secret leakage.

**Verification:** `.venv/bin/python -m pytest backend/tests/test_openrouter_engine.py -q`

**Dependencies:** OR-00.

**Files likely touched:** `backend/app/services/openrouter.py`, `backend/tests/test_openrouter_engine.py`.

**Estimated scope:** S/M, 2 files.

### OR-02: Add write-only secret, model config, and capability

**Description:** Make OpenRouter configurable and diagnosable without exposing its secret or implying that a paid generation was tested.

**Acceptance criteria:** secret allowlist never returns value; validated free-text model; key/config capability does not claim paid live success; connection test is cheap or honest; existing engine arrays/order unchanged.

**Verification:** config, capability, settings, and provider tests.

**Dependencies:** OR-01.

**Files likely touched:** config, capability, settings route, tests; split if >5 files.

**Estimated scope:** M, 4–5 files.

### OR-03: Wire OpenRouter into generation with consent and provenance

**Description:** Add an append-only provider lane to existing generation orchestration while retaining remote-consent, NSFW, provenance, and no-fallback guarantees.

**Acceptance criteria:** append-only engine ID; generation/regeneration/fan-out/activity/failure recovery support; remote consent; NSFW fail-closed local; fatal/per-image errors defined; no provider fallback; credential-free provenance.

**Verification:** `.venv/bin/python -m pytest backend/tests/test_openrouter_engine.py backend/tests/test_dataset_service.py backend/tests/test_dataset_routes.py backend/tests/test_engines.py -q`

**Dependencies:** OR-01, OR-02.

**Files likely touched:** face service and up to three tests.

**Estimated scope:** M, 3–4 files.

### OR-04: Add honest Settings and Setup surfaces

**Description:** Provide write-only credential/model controls and current privacy/setup guidance while keeping the provider disabled by default.

**Acceptance criteria:** write-only key/model field; status distinguishes configured from live-tested; privacy card names OpenRouter; official links current; off by default.

**Verification:** focused registry/setup tests and `cd frontend && pnpm run gate`.

**Dependencies:** OR-02.

**Files likely touched:** settings engine section/registry, setup steps, tests; ≤5 files.

**Estimated scope:** M.

### OR-05: Add explicit provider/model selection UI

**Description:** Expose the configured billed provider/model only when capable, without changing existing engine behavior or inventing a stale price.

**Acceptance criteria:** only enabled/capable; provider/model billing identity named; existing engine order/behavior unchanged; no invented price; refs/prompt not silently changed.

**Verification:** focused engine/prompt tests and `cd frontend && pnpm run gate`.

**Dependencies:** OR-03, OR-04.

**Files likely touched:** pure selection utility/test, Variation Catalog, prompt helper/test; split if >5.

**Estimated scope:** M.

### OR-06: Pass the full live release gate

**Description:** Re-run success and representative provider failures through the complete app and inspect every persistence/logging/browser boundary for secret leakage.

**Acceptance criteria:** app success plus invalid key, no credit, unknown model, rate limit, refusal, consent-disabled; logs/diagnostics/API/DB/browser inspected for secrets; billed provider/model matches UI; feature stays off until all pass.

**Verification:** redacted live evidence and human approval.

**Dependencies:** OR-05.

**Files likely touched:** verification record only.

**Estimated scope:** External gate.

### Checkpoint OR: OpenRouter release gate

- [ ] Official-docs/live spike, adapter, configuration, service integration, and UI are complete in order.
- [ ] Authorized live success and invalid-key/no-credit/model/rate/refusal/consent-disabled cases pass.
- [ ] Logs, diagnostics, API responses, database provenance, and browser payloads contain no secret.
- [ ] Provider/model billed in the live account matches the UI and persisted provenance; feature stays off by default until human approval.

---

## Final Program Closure

- [ ] Every adopted task has a merge commit/commit SHA and focused test evidence.
- [ ] All required checkpoints pass on the supported toolchain.
- [ ] UI changes have genuine before/after screenshots ready before any public issue/PR/release.
- [ ] No secrets, personal paths, external-facing assistant attribution, or generated evidence presented as a real screenshot.
- [ ] README/guide/release notes describe only shipped and verified behavior.
- [ ] Deferred epics remain disabled/unadvertised and retain their explicit gates.
- [ ] Human signs off release scope, rollback plan, and known limitations.

---

## CI Recovery Tasks — 2026-08-29

Implementation is in progress. The detailed design, current state, and verification commands are in the `CI Recovery Plan` section of `tasks/plan.md`.

### CI-01: Restore the canonical guide launch reference

- [x] Replace the redundant `#open-the-app` Markdown link with the exact absolute README `#installation-and-launch` target.
- [x] Add a repository-contract regression test for a missing or altered canonical target.
- [x] Rebuild generated `frontend/dist` output and verify its asset graph has no missing or stale files.
- [x] Run the focused governance and frontend DOM-link tests.

**Files:** `docs/guide/getting-started.md`, `tests/test_repository_contracts.py`, generated `frontend/dist/**`.

**Done when:** both the frontend guide-link contract and repository governance validator pass from the same source wording.

### CI-02: Make the forced-probe concurrency test hermetic

- [x] Stub the live `_http_ok` network seam and give the spawned child isolated config/data paths under `tmp_path`.
- [x] Stub direct provider `requests.get` calls so environment-selected LM Studio or llama.cpp cannot reach the network.
- [x] Replace fixed sleeps with an instrumented `_probe_lock` entry barrier that proves all callers captured the same cache generation before refresh begins.
- [x] Isolate the thread harness in a spawned process, capture worker exceptions, and terminate the child safely if the five-second parent deadline expires.
- [x] Assert an exact cache-generation delta so three callers provably share one refresh.
- [x] Pass the Windows Python 3.10 CI job, then rerun that successful job twice through `gh`.

**Files:** `backend/tests/test_capabilities.py` initially; `backend/app/capabilities.py` only after a deterministic production-bug reproduction.

**Depends on:** CI-01 may run independently; complete both before the full gate.

**Done when:** repeated focused runs pass without increasing timeouts or weakening the single-refresh assertion.

### CI-03: Validate and push the atomic recovery

- [x] Run the complete supported backend and frontend validation suites for the atomic recovery change.
- [x] Use the exact repository-native commands listed in Phase 3 of `tasks/plan.md`.
- [x] Confirm generated output is current and the worktree is clean after commits.
- [x] Inspect outgoing commit metadata for neutral, task-focused wording.
- [x] Push `main` and watch every GitHub Actions job to completion.
- [x] Record any remaining non-blocking warning with its upstream constraint.

**Depends on:** CI-01 and CI-02.

**Done when:** the recovery GitHub Actions run and both Windows Python 3.10 reruns are green, establishing the baseline required by CI-04.

### CI-04: Refresh GitHub Actions runtime pins

- [x] Verify the smallest maintained Node 24-compatible releases and immutable SHAs from official action sources.
- [x] Read intervening release notes and migration guidance for every upgraded action.
- [x] Update matching pins and version comments in CI and release workflows.
- [x] Preserve action inputs; all referenced actions have a maintained Node 24-compatible release.
- [x] Run repository-governance validation locally; workflow syntax is delegated to the pinned GitHub `actionlint` job because no local binary is installed.

**Files:** `.github/workflows/ci.yml`, `.github/workflows/release.yml`.

**Depends on:** CI-03 establishes a green pushed recovery run plus two green Windows 3.10 reruns; land as a separate maintenance commit.

**Done when:** supported action pins are current, immutable, consistent, and the workflows validate.

### CI-05: Validate and push the action-pin maintenance

- [x] Run the focused workflow/governance checks and applicable complete local gate.
- [ ] Commit only the reviewed action pins, migration-required input changes, and final checklist state.
- [ ] Push `main` and watch every ordinary CI job to completion.
- [ ] Confirm the governance actionlint step executes successfully.
- [ ] Record the tag-only release workflow's remaining live-release verification boundary.

**Depends on:** CI-04.

**Done when:** the post-maintenance GitHub Actions run is green and every in-scope Node 20 warning is gone or explicitly accepted because no maintained compatible release exists.

### Accepted warning follow-ups

- [ ] Plan React Router v7 future-flag/migration work separately from CI recovery.
- [ ] Review pnpm's ignored-build-script policy separately and explicitly approve only dependency scripts the project requires.
