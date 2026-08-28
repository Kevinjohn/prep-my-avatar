# Implementation Plan: Selective Upstream Adoption

## Status

- Planning baseline: fork `7cd3055df7` on 2026-08-28.
- Closest upstream source snapshot: `7be0d0684675297892a9a2393bc3d92a68905da2`.
- Upstream repository: `perfectgf/lora-dataset-studio` (GitHub); full local clone with every cited commit at `~/Documents/GitHub/lora-dataset-studio-upstream`.
- Upstream release window reviewed: `v2026.07.16` through `v2026.08.27.1` (46 releases).
- Integration strategy: semantic ports pinned to upstream commits, never a wholesale merge or blind cherry-pick.
- Implementation may not start until a human approves the Adopt-now scope and selects the Klein variant policy. Later review, validation, and release gates are listed in the gate tables below.
- **Approved 2026-08-28:** the `Adopt now` scope is approved as listed, and the Klein policy is an explicit allowlist recorded at `BASE-00` — only variants that pass the live `ST-10` gate are advertised; supporting both 4B and 9B requires both to pass independently.

## Human and Operator Gates

| Gate | When | Who | Nature |
|---|---|---|---|
| BASE-00 approval | Before implementation | Human | Product decision (granted 2026-08-28) |
| Checkpoint 1 resolver contract | Wave 1 exit, before any ST-01 consumer merges | Human | Contract review |
| Checkpoint 2/3 manual protocols | Wave exits | Supervisor or authorized operator | Evidence gate |
| ST-10 / Checkpoint 4 real ComfyUI run | Before CORE release | Authorized operator | Evidence gate |
| CORE release approval | Checkpoint CORE | Human | Release decision |
| Corpus release validation | Checkpoint CW | Supervisor + human release sign-off | Release decision |
| GA-00 / SV-00 / OR-00 approvals | Before each optional epic | Human | Product decision (not yet granted) |

## Outcome

Adopt the upstream changes that materially improve correctness and reliability without importing the upstream product's much larger Image Bank, Canvas, Video Bank, extension-loader, or full-model-training architecture.

The first releasable program delivers five outcomes:

1. Test Studio discovers the same deployed LoRA files that training writes, refuses unsupported families honestly, and can execute a real FLUX.2 Klein lane.
2. Hand-written captions have durable authorship and are protected from bulk re-captioning unless the user explicitly overrides that protection.
3. Technical sharpness scoring recognizes a sharp subject against a blurred background without allowing a single artifact tile to certify a blurred image.
4. A tab left open across an update recovers from stale hashed frontend chunks with one bounded reload.
5. Corpus review receives search, sorting, and per-dataset resume state after the correctness work is stable.

Gallery, SeedVR2, and OpenRouter remain separately gated optional epics. Their tasks are defined so they can be approved and delegated later without reopening the core plan.

## Upstream Evidence Map

Offline copies: every cited commit is extracted as a readable patch in `tasks/upstream-evidence/`
(index in `tasks/HANDOFF.md`), with key upstream files and the Klein t2i workflow snapshot under
`tasks/upstream-evidence/snapshot-7be0d068/`, and ComfyUI model-path reference sources under
`tasks/upstream-evidence/comfyui-reference/`. The full upstream clone is at
`~/Documents/GitHub/lora-dataset-studio-upstream`.

| Area | Upstream commit(s) | Porting decision |
|---|---|---|
| Studio family discovery | `218d4b7134d20b93840f18fb374cbefc1fd02dd1` | Adopt the invariant and tests; adapt to this fork's five-family registry and split service modules. |
| FLUX.2 Klein Studio | `b6f64bd09f51d7a803b75253be29d20d8a2a6941` | Adopt the lane, workflow principles, whitelists, and honest refusal; resolve assets through this fork's `klein_edit_helper`. |
| Caption authorship | `945b2631889a4d5a462a6df8718d4f806a1b5cbd` | Adopt only dataset-image authorship; do not import Image Bank or short-caption concepts. |
| Caption author labels | `63b6f634c6e1e82d2ccf9d01fb04ab6e4d233b34` | Adopt dataset API/UI labels only. |
| Manual-caption protection | `14a2aedb26dc9ab9cbe6473926c9e17b1b96ea18` | Adopt for character, concept, and style lanes, including the mid-inference edit guard. |
| Bokeh-aware sharpness | `f1694e05a2f5ac8eceff861b10acc2dbfa343a9b` | Adopt tiled p90 semantics, but preserve this fork's bounded 0-100 score and recalibrate with fork-specific fixtures. |
| Stale lazy chunks | `2df5becd4bb5f277dc0d02e3118ff2258f0189e0` | Adopt the one-shot reload wrapper; this fork already has route-level code splitting. |
| Gallery | `b4fe442`, `216d4dd`, `32e87ff` | Optional fork-native aggregation over existing dataset/Studio rows; do not import upstream Bank/Canvas. |
| SeedVR2 | `8606832fa6eb2d2e307b6815252da3cbb25fac15`, `17a1dda6e380afb2a0e1ef294bc065a459563155` | Optional only after dependency/license and real-GPU gates. |
| OpenRouter | `068732e60d8a0c39f352c4e0f5069c54c3f33cda` | Optional only after an official-docs/live-contract spike; upstream explicitly lacked live verification. |

## Scope Decision

### Adopt now

- Canonical multi-root ComfyUI model and LoRA discovery.
- Studio family/deployment parity and removal of all silent Z-Image fallbacks.
- FLUX.2 Klein text-to-image Test Studio lane.
- Caption authorship, atomic metadata writes, author display, and asserted-caption protection.
- Bokeh-aware tiled sharpness scoring with versioned, explicit refresh.
- One-shot stale lazy-chunk recovery.

### Adopt after the core release

- Corpus Workbench search, deterministic sorting, honest empty states, and per-dataset resume state.

### Optional, separately approved epics

- Read-only Gallery and selection ZIP; destructive Gallery deletion is an additional gate.
- SeedVR2 improvement engine; automatic tiling is a post-launch sub-epic.
- OpenRouter generation provider.

### Explicit non-goals

- Whole upstream Image Bank, LoRA Canvas, Video Bank, full-model training, fp8 training, RunPod studio, extension loader, camera-angle/Civitai prompt packages, Safelight/React 19 migration, Anima, or non-human datasets.
- Replacing this fork's privacy consent, token gate, process locking, update rollback, trash, backup, integrity, or CI systems, which already cover the corresponding upstream value.
- Silent fallback between model families, caption engines, image-improvement engines, or paid remote providers.

## Architecture Decisions

### A1. Semantic ports, not cherry-picks

The repositories have no usable common Git ancestry and the fork has split several upstream monoliths into services. Each task cites upstream behavior as evidence, then implements the smallest equivalent contract in the fork's current architecture. Every PR/commit must remain independently reversible.

### A2. One model-root contract

A single backend resolver owns ComfyUI search roots, write roots, aliases, listing, safe loader-relative resolution, priority, de-duplication, and `extra_model_paths.yaml`. Deployment, picker listing, architecture inspection, preflight, and Klein model resolution must consume it. An absolute or traversal reference fails closed.

### A3. Visible families are not executable lanes

The fork's deployable families are exactly `zimage`, `sdxl`, `krea`, `flux`, and `flux2klein`. Studio generation families are a strict subset. `flux2klein` joins that subset only in the same commit that adds its executable graph. `flux` remains known but unsupported until it has an explicit engine configuration.

### A4. Caption origin is coarse authorship; provenance remains detailed evidence

`caption_origin` is nullable and uses `asserted`, `joycaption`, or `ollama`. `NULL` means “not recorded,” never “machine.” `caption_provenance` continues to carry model/revision/seed evidence. A central helper writes caption text, origin, and provenance atomically.

### A5. Human edits win

An ordinary forced batch rewrites machine and legacy-unknown captions while sparing non-empty `asserted` captions. Replacing asserted captions requires an explicit, unchecked override. If a caption changes while inference is running, the later model result is discarded even when the override was selected at launch.

### A6. Sharpness remains a bounded public score

The algorithm changes from whole-frame edge variance to the 90th percentile of tile Laplacian variances. The outward score stays an integer from 0 to 100 so existing consumers remain compatible. `analysis_version` increases, existing v1 rows are not rewritten on startup or GET, and the existing explicit “Refresh local analysis” action upgrades them.

### A7. Frontend generated output has one owner

Frontend source work can occur in parallel worktrees, but parallel agents must not each merge regenerated `frontend/dist`. The integration owner merges source commits, runs `pnpm run gate`, and commits the single resulting dist update at the checkpoint. If repository policy requires dist in each source commit, frontend tasks are landed serially instead.

### A8. External engines fail at gates, not in production

SeedVR2 begins with exact dependency/license/model-hash and real-GPU evidence. OpenRouter begins with current official documentation and a redacted, authorized live request. Neither gets config, UI, or a shipping claim before its spike passes.

## Dependency Graph

```text
CORE PROGRAM

Comfy roots ST-01
  ├─ family registry ST-02 ── Studio discovery ST-03
  ├─ Studio preflight ST-04
  └─ Klein catalog ST-06
ST-03 + ST-04 ── honest lanes ST-05
ST-03 + ST-04 + ST-05 + ST-06 ── Klein graph ST-07
ST-07 ── API/payload ST-08 ─┬─ frontend ST-09
                            └─ integration ST-10

Caption schema CA-01 ── helper CA-02 ── human/copy paths CA-03
                                      └─ API payload CA-05 ── UI semantics CA-06
CA-03 ── inference protection CA-04
CA-04 + CA-06 ── UI author display CA-07 ── recaption UX CA-08

Sharpness fixtures QS-01 ── tiled backend QS-02 ── prototype parity QS-03
                                             └─ stale-version UI QS-04

Lazy loader LZ-01 ── route integration LZ-02

CORE CHECKPOINT ── Corpus CW-01 ── CW-02 ── CW-03
```

Optional epics are isolated behind the core checkpoint:

```text
Gallery decision GA-00 ── read API GA-01 ── media/ZIP GA-02
                                      ├─ deletion GA-03 [extra approval]
                                      └─ frontend state GA-04 ── page GA-05 ── nav/actions GA-06

SeedVR2 spike SV-00 ── capability SV-01 ── graph SV-02 ── dispatch SV-03
                                              ├─ completion/QA SV-04
                                              ├─ setup SV-05 ── UI SV-06
                                              └─ tiling SV-07 ── hardware gate SV-08

OpenRouter spike OR-00 ── adapter OR-01 ── config/capability OR-02
                                        ├─ generation integration OR-03
                                        └─ settings OR-04 ── selection UI OR-05 ── live gate OR-06
```

## Delivery Waves and Subagent Assignments

The maximum useful topology is one supervising/integration agent plus three implementation agents. All implementation work should use isolated worktrees or serial commits; agents must never edit the same shared checkout concurrently.

### Wave 0 — approval and baseline

- Supervisor: confirm the two open decisions, run clean baseline gates, record versions and any pre-existing failures.
- Exit: clean baseline or an approved list of pre-existing failures with logs.

### Wave 1 — independent foundations

- Agent A: `ST-01` canonical ComfyUI paths.
- Agent B: `CA-01` then `CA-02` caption schema/helper, as one combined brief with separate commits.
- Agent C: `QS-01` then `QS-02` sharpness fixtures/backend algorithm, as one combined brief; `QS-01` remains the independently reviewable failing-contract commit.
- Supervisor: review public contracts; run Checkpoint 1.

These assignments do not share source files. Related S tasks assigned to one agent are delivered as one delegated brief while retaining their task and commit boundaries (`CA-01`+`CA-02`, `QS-01`+`QS-02`, `LZ-01`+`LZ-02`).

### Wave 2 — independent vertical slices

- Agent A: `ST-02`, `ST-04`, and `ST-06` in separate commits.
- Agent B: `CA-03`, `CA-04`, and `CA-05` sequentially; this agent owns `face_dataset_service.py` exclusively.
- Agent C: `QS-03` in the Python/backend footprint (`src/avatar_prep/core.py`, `tests/test_core.py`, and the shared backend fixture test), then `LZ-01` and `LZ-02` (one combined brief) in the frontend footprint.
- Supervisor: merge backend commits first, frontend source next, regenerate dist once, run Checkpoint 2.

### Wave 3 — Studio serialization and frontend completion

- Agent A: `ST-03`.
- Agent B: `CA-06` through `CA-08` sequentially.
- Agent C: `QS-04`.
- Supervisor: integrate frontend source, rebuild dist, run Checkpoint 3.

### Wave 4 — Klein backend serial chain

- One exclusive Studio agent: `ST-05`, then `ST-07`, then `ST-08`.
- Another agent may prepare read-only fixture review, but must not edit Studio hotspot files.
- After `ST-08`, parallelize `ST-09` frontend and `ST-10` backend integration.
- Supervisor: run the complete core gates and the real ComfyUI acceptance protocol.

### Wave 5 — low-risk product enhancement

- One frontend agent owns `CW-01` through `CW-03` sequentially.
- Supervisor regenerates dist and runs the Corpus checkpoint.

### Later waves

- Gallery: backend `GA-01`/`GA-02` and frontend `GA-04` can overlap only after `GA-00`; `GA-03` requires separate approval; `GA-06` follows `LZ-02` because both touch `App.jsx`.
- External engine: choose SeedVR2 or OpenRouter, not both at once. They share config, capability, settings, service, and dist hotspots.

## Checkpoints

### Checkpoint 0 — clean baseline

```bash
git status --short
.venv/bin/python -m pytest backend/tests -q
.venv/bin/python -m pytest tests -q
.venv/bin/python -m ruff check backend src tests
cd frontend && pnpm run gate
```

Record runtimes and failures before implementation. Do not relabel a new failure as pre-existing without this evidence.

### Checkpoint 1 — foundations

```bash
.venv/bin/python -m pytest \
  backend/tests/test_comfy_model_paths.py \
  backend/tests/test_caption_origin.py \
  backend/tests/test_import_analysis.py -q
.venv/bin/python -m ruff check backend src tests
```

Review the caption-origin vocabulary, SQL `NULL` behavior, synthetic image fixtures, and analysis score scale before dependent agents proceed.

**Resolver contract gate:** a human must review and approve the `ST-01` public resolver contract — search/write roots, aliases, priority, de-duplication, loader-relative identifiers, refresh behavior, and fail-closed path handling — before `ST-02`, `ST-03`, `ST-04`, `ST-06`, or any other resolver consumer is merged.

### Checkpoint 2 — backend behavior and lazy recovery

```bash
.venv/bin/python -m pytest \
  backend/tests/test_family_pool_parity.py \
  backend/tests/test_studio_preflight.py \
  backend/tests/test_klein_models.py \
  backend/tests/test_caption_asserted_protection.py \
  backend/tests/test_captioning.py \
  backend/tests/test_curation_history.py \
  backend/tests/test_dataset_routes.py \
  backend/tests/test_import_analysis.py \
  backend/tests/test_image_improve.py \
  tests/test_core.py -q
cd frontend && pnpm run gate
```

Manually verify one-shot stale-chunk recovery with build A replaced by build B, then with a genuinely missing build-B chunk to prove there is no loop.

### Checkpoint 3 — caption/sharpness UI

```bash
.venv/bin/python -m pytest backend/tests/test_caption_asserted_protection.py backend/tests/test_dataset_routes.py -q
cd frontend && pnpm run gate && pnpm run e2e
```

Manual caption protocol:

1. Generate captions with both configured engines where available.
2. Edit one by hand and leave one legacy/unknown fixture.
3. Run ordinary Re-caption: machine and unknown change; asserted stays byte-identical.
4. Run the explicit asserted override: the confirmation names the destructive scope.
5. During a slow mocked/live caption, edit another caption and confirm the manual text survives.
6. Backup/restore and undo a manual edit; confirm text, origin, and provenance stay atomic.

Manual sharpness protocol:

1. Import a sharp-subject/bokeh image, a uniformly blurred copy, and an artifact-speck fixture.
2. Confirm only the bokeh portrait clears the sharpness threshold.
3. Open a v1 dataset; confirm it is marked outdated rather than silently changed.
4. Use “Refresh local analysis”; confirm the notice clears and face/coverage metadata is preserved.

### Checkpoint 4 — core complete

```bash
.venv/bin/python -m pytest backend/tests -q
.venv/bin/python -m pytest tests -q
.venv/bin/python -m ruff check backend src tests
.venv/bin/python -m pip_audit -r backend/requirements.txt --progress-spinner off
.venv/bin/python -m pip_audit -r backend/requirements-scrape.txt --progress-spinner off
.venv/bin/python -m pip_audit -r backend/requirements-ml.txt --progress-spinner off
cd frontend && pnpm run gate && pnpm audit --prod --audit-level high && pnpm run e2e
git status --short
```

Also complete the real ComfyUI Klein acceptance gate defined in `ST-10`, executed exactly per `tasks/ST-10-RUNBOOK.md` (environment record, asset hashes, fixed prompt/seed protocol, evidence destination). Automated graph tests are necessary but cannot prove model compatibility.

### Checkpoint 5 — Corpus UX

```bash
cd frontend
pnpm exec node --test \
  src/utils/corpusWorkbenchState.test.js \
  src/components/dataset/CorpusWorkbench.test.js
pnpm run gate
pnpm run e2e
```

Manually review keyboard behavior, two-dataset state isolation, corrupt storage recovery, and a 200-image corpus.

**Corpus release gate (lightweight):** record the CORE release SHA. After `CW-01` through `CW-03`, run the focused CW tests, `pnpm run gate`, `pnpm run e2e`, and the documented manual Corpus protocol, then prove that no backend or Python implementation changed since CORE:

```bash
git diff --exit-code <CORE_RELEASE_SHA>..HEAD -- backend src tests pyproject.toml
```

If that diff is non-empty, the Corpus batch loses lightweight status and the affected CORE checks are selected according to the changed files. An empty diff means the CORE backend pytest, Ruff, and three `pip_audit` gates are not rerun.

## Release Batches

| Release boundary | Scope | Required gate |
|---|---|---|
| CORE (batch 1) | ST, CA, QS, LZ | Full Checkpoint CORE matrix, audits, e2e, manual protocols, real ComfyUI |
| Corpus (batch 2) | CW-01..03 | Focused CW tests, frontend gate/e2e, manual protocol, empty backend diff |
| Gallery | GA tasks | Checkpoint GA after separate approval |
| SeedVR2 | SV tasks | Checkpoint SV after dependency/license/hardware approval |
| OpenRouter | OR tasks | Checkpoint OR after docs/live-contract authorization |

## Merge and Commit Policy

- One task equals one focused commit unless a task explicitly says it is an integration-only verification task.
- Every commit message is neutral and task-focused; no assistant attribution or internal identifiers.
- Every agent rebases/updates its worktree before handoff and reports the commit SHA, files changed, focused commands, and results.
- The supervisor reviews every diff before merge and runs checkpoint gates after each integration wave or serialized hotspot group.
- Migration numbers are assigned at merge time. A published migration is never renumbered or removed.
- Frontend UI commits include regenerated `frontend/dist` according to `CONTRIBUTING.md`; use one integration owner to avoid generated-output conflicts.
- No task may silently broaden a shared type, family registry, engine list, or public API beyond its stated acceptance criteria.

## Standard Subagent Brief

Every delegated implementation prompt should contain:

```text
You are implementing task <ID> from tasks/todo.md under a supervising session.
Read first: tasks/HANDOFF.md, CONTRIBUTING.md, and task <ID> in tasks/todo.md; consult the
task's evidence file in tasks/upstream-evidence/ (mapped in HANDOFF.md). Assume no internet.
Decision and approach are fixed by the task; do not redesign adjacent contracts.
Files in play: <exact list>. Do not touch other files without reporting BLOCKED.
Implement acceptance criteria, add focused tests, and run only the task's focused
tests plus a clean typecheck/formatter check required by AGENTS.md. Use pnpm only.
Commit the work. Return DONE with commit SHA, changed files, commands/results,
manual checks not run, and residual risks; or BLOCKED with exact evidence.
Do not publish, push, open issues/PRs, or include external-facing attribution.
```

For tasks that use an external service or GPU, add the exact authorized credential, spend, download, data, and hardware boundaries. Absence of any boundary is a blocker, not permission to improvise.

## Conflict Matrix

| Areas | Conflict | Coordination rule |
|---|---:|---|
| `ST-03`, `ST-05`, `ST-07` | High: `studio_discovery.py` | Strictly serial. |
| `ST-04`, `ST-05`, `ST-07` | High: `lora_test_studio.py` | Strictly serial and one Studio owner. |
| `ST-05`, `ST-08` | Medium/high: payload/routes | `ST-05` first. |
| `CA-03`, `CA-04`, `CA-05` | High: `face_dataset_service.py` | Same agent, sequential commits. |
| Caption UI and Corpus UX | High: `DatasetWorkspace.jsx` / dist | Finish caption UI before Corpus. |
| `QS-04` and `CW-01`/`CW-02` | High: `CorpusWorkbench.jsx` / dist | `QS-04` lands before CORE; Corpus remains gated behind CORE. |
| Lazy recovery and Gallery nav | High: `App.jsx` / dist | `LZ-02` before `GA-06`. |
| Any parallel frontend tasks | High: generated dist | One integration rebuild. |
| SeedVR2 and OpenRouter | Very high: config, capabilities, service, settings | Choose and serialize whole epics. |
| Sharpness and all Studio work | Low | Safe to parallelize. |

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---:|---|
| Model path semantics differ from ComfyUI | High | Fixture matrix for default/extra roots, aliases, priority, case, traversal, malformed YAML; one resolver for every consumer. |
| Klein 4B/9B incompatibility is hidden | High | Variant-specific catalog and real smoke; block or label unsupported variant rather than infer support. |
| Caption migration mislabels legacy data | High | Leave existing rows `NULL`; SQL tests distinguish unknown from machine; no backfill. |
| In-flight inference overwrites a human edit | High | Capture planned tuple, reload before write, compare, and skip changed/deleted rows. |
| New sharpness scale changes admission too broadly | High | Preserve 0-100 scale, deterministic synthetic fixtures, explicit v2, manual threshold review, no automatic rewrite. |
| Frontend reload loops | High | Session-scoped one-shot guard, storage-failure tests, second failure rethrows to ErrorBoundary. |
| Parallel agents create an unmergeable diff | Medium | File ownership, serialized hotspots, isolated worktrees, one dist owner, checkpoints. |
| Gallery deletion breaks reconstruction pairs or Studio history | High | Read-only MVP first; deletion has its own human/restore gate. |
| SeedVR2 adds unlicensed or incompatible assets | High | Exact revisions, hashes, licenses, no silent node installation, explicit large-download approval, real GPU gate. |
| OpenRouter mocks diverge from the live API | High | Official-docs/live spike before code, redacted fixture, explicit spend and privacy consent. |

## Resolved Decisions (approved 2026-08-28)

1. **Klein variants:** explicit allowlist recorded at `BASE-00`. Only variants that pass the live `ST-10` real-ComfyUI gate are advertised; unvalidated variants remain unadvertised. Supporting both 4B and 9B requires both to pass independently.
2. **Core scope:** the `Adopt now` program is approved as one roadmap, with Corpus as the immediately following lightweight release (batch 2). Gallery, SeedVR2, and OpenRouter stay unapproved until their individual gates are reviewed.

## Definition of Done

A task is complete only when:

- its acceptance criteria are demonstrated by tests or the named manual protocol;
- its focused verification, formatter/lint, and required typecheck pass;
- no unrelated files changed;
- public contracts and migrations are backward compatible as specified;
- tests assert observable outcomes, not merely that helper functions were called;
- user-visible UI has keyboard/accessibility coverage and screenshots before publication;
- external failures are explicit, typed, and do not fall back to another family/engine/provider;
- its commit is reviewable and independently revertible;
- the supervising checkpoint passes after merge;
- the human approves this plan before implementation begins.

