# Simplify sweep — standing goal

Paste the **Goal prompt** below into a session to run one pass. The ledger at the
bottom is the resume point, so a fresh session can pick up wherever the last one
stopped. One pass per session; do not attempt the whole sweep in one context.

---

## Goal prompt

> You are running one pass of the simplify sweep defined in `SIMPLIFY-SWEEP.md`.
>
> Read that file, consult the ledger, and take the **first pass whose status is
> `todo`**. Do not skip ahead, do not batch two passes, and do not start a pass
> whose predecessor is `blocked` without telling me why you are proceeding anyway.
>
> Run the pass exactly as the Per-pass protocol specifies: capture a green
> baseline, fan out the four review lenses over that pass's file set, dedup the
> findings, verify each surviving one yourself against the actual code before
> acting on it, apply what survives, re-run the gates, and commit.
>
> Then update the ledger in `SIMPLIFY-SWEEP.md` — status, commit SHA, and a one
> line note on what was found — and stop. Report what you fixed, what you skipped
> and why, and whether the gates passed. Do not start the next pass.
>
> If the gates were red before you touched anything, fix nothing, mark the pass
> `blocked`, and tell me.

---

## Why this exists

`/simplify` is diff-scoped: it reviews `git diff`, not a codebase. Pointed at a
repo with no relevant diff it reviews whatever happened to change last. This
sweep supplies the scope instead — a fixed set of cohesive file groups, reviewed
one at a time, each behind a test gate.

The four lenses are **reuse**, **simplification**, **efficiency**, and
**altitude**. This is a quality pass, not a bug hunt; `/code-review` covers
correctness.

## Non-negotiables

1. **One pass, one commit.** Never combine two passes into a single commit. When
   a pass makes something worse, reverting must cost one `git revert`.
2. **Gates before and after.** Capture a green baseline *before* editing. If the
   baseline is already red, stop and mark the pass `blocked` — never edit on top
   of a red suite, because then you cannot tell whose failure it is.
3. **Verify every finding against the code before acting on it.** Subagents
   report plausible things that are not true. Open the file and confirm the
   claim. An unverified finding is a rumour.
4. **Skip liberally.** The lenses are phrased around what *a diff adds*. Aimed at
   files that have been stable for a year, they will flag settled code as if it
   were new. Skip anything whose fix would change behaviour, needs edits well
   outside the pass, or is just a differently-shaped version of what is there.
   Note the skip; do not argue with it.
5. **Never touch `frontend/dist/` by hand.** It is a committed build artifact.
   Rebuild it only when a pass changed something that feeds the bundle.
6. **Stop and ask** if a pass wants an architectural change, a public API or
   schema change, or if gates go red and the cause is not obvious in one look.

## Gates

**Backend** (95 test files under `backend/tests`). Use the repo `.venv`
interpreter explicitly — bare `python` does not resolve under pyenv on this
machine, and `python3` is a 3.14 install without the dependencies:

```bash
.venv/bin/python -m pytest backend/tests -q
```

Check the exit code directly rather than eyeballing piped output; `| tail` masks
a failure as exit 0. Green baseline as of 2026-08-14: 1740 passed, 1 skipped.

Note `pyproject.toml` sets `filterwarnings = ["error"]` — a new warning fails the
suite. That is intended; do not silence it to get green.

**Frontend** (from `frontend/`):

```bash
npm run lint && npm run typecheck && npm run test && npm run build && npm run check:bundle
```

Run only the side a pass actually touched. `check:bundle` matters on any pass
that changes what ends up in the bundle.

## Per-pass protocol

1. **Sync.** `git fetch`, confirm a clean tree and no incoming commits. Never
   trust repo state from earlier in the conversation.
2. **Baseline.** Run the gates for the side being touched. Record the result. Red
   baseline → mark `blocked`, stop.
3. **Scope.** Resolve the pass's file list. Report the real line count; if it has
   drifted far above ~4,000 lines, split the pass and say so.
4. **Review.** Launch the four lenses in parallel in a single message, each over
   the same file set. Give each agent the file list, the repo conventions, and an
   explicit instruction to return `file`, `line`, a one-line summary, and the
   concrete cost — and to say plainly when it finds nothing rather than
   manufacturing findings.
5. **Dedup and verify.** Collapse findings that point at the same mechanism. Then
   check each survivor against the actual code yourself.
6. **Apply.** Fix what survived. Prefer the smallest change that removes the
   duplication or complexity.
7. **Re-gate.** Run the gates again. They must be as green as the baseline.
   Rebuild `frontend/dist/` if the pass changed bundled input.
8. **Commit** with a message explaining *why* each change was made, not just
   what. Push if the tree is clean and gates are green.
9. **Update the ledger** and stop.

## Lessons from completed passes

Learned the hard way in pass 1. Read before starting.

- **A lens agent can read the shape and miss the constraint.** Pass 1's
  highest-rated altitude finding was "replace the engine `if` chains with a
  registry" — wrong, because those provider imports are deliberately lazy
  (optional dependencies) and a module-level registry of function references
  would force them eager. Before acting on any "collapse this into a table"
  finding, check *why* the branches exist.
- **Check for re-exports before deleting a now-unused import or constant.**
  Pass 1 nearly dropped `_hamming` and `SCRAPE_DHASH_MAX_DISTANCE` as orphans;
  `lora_training.py` and the scrape tests reach through this module for both.
  Always grep repo-wide, not just the file.
- **A "duplicate" that has already drifted is the best kind of finding.** Where
  pass 1 found three copies of the same JSON parse, they were not identical —
  one caught fewer exception types. Drift is the proof the duplication costs
  something.
- **Prefer findings that delete code.** Pass 1's net was −47 lines with zero
  behaviour change. Anything that adds abstraction to remove a little repetition
  should clear a higher bar.
- **The ledger cannot record its own commit SHA.** Either commit the pass and
  update the ledger in a small follow-up commit, or write the SHA in afterwards.

### Carried-over findings

Real, verified, deferred because they fell outside their pass's scope. Fold each
into the pass named, rather than rediscovering it.

- **Pass 9 (`analysis-quality`): every imported photo is decoded twice.**
  `analyse_image_bytes` (`import_analysis.py`) and `normalize_to_webp` /
  `face_crop_to_square_webp` (`image_processing.py`) each independently run
  `Image.open` → `ImageOps.exif_transpose` → `convert('RGB')` on the same raw
  bytes, from `import_images` and `_merge_training_images`. That is 2× full
  decode per photo on every import, scaling with corpus size — the largest
  single efficiency finding in the sweep so far. The fix changes both modules'
  APIs to accept an already-decoded image, which is why pass 1 left it.
- **Pass 1 follow-up, structural:** the two caption pipelines (`caption_images`
  and `_caption_concept`) duplicate a whole JoyCaption→Ollama orchestration, and
  the coverage-state classifier (`covered`/`weak`/`missing`/`unknown`) is
  hand-written three times with different rules — one path cannot produce
  `unknown` at all. Both need dedicated passes with their own test coverage.

## Passes

Grouped so that files which call each other are reviewed together — the reuse and
altitude lenses only produce real findings when siblings are visible at once.
Line counts are from 2026-08-14 and will drift.

### Wave 1 — backend, highest payoff

| # | Pass | Scope | ~Lines |
|---|---|---|---|
| 1 | `face-dataset-service` | `backend/app/services/face_dataset_service.py` | 6,711 |
| 2 | `lora-training-core` | `services/lora_training{,_process,_queue,_config_builder,_settings,_checkpoints,_export}.py`, `training_snapshot.py`, `training_jobs.py` | 5,136 |
| 3 | `remote-training-publish` | `services/cloud_training.py`, `vast_client.py`, `aitoolkit_remote.py`, `hf_publish.py`, `run_share.py`, `checkpoint_registry.py` | 4,080 |
| 4 | `generation-engines` | `services/face_variations.py`, `klein_edit_helper.py`, `chatgpt_image.py`, `chatgpt_oauth.py`, `nanobanana.py`, `comfyui_service.py`, `zimage_convert.py`, `utils/comfyui.py`, `utils/zimage_helper.py` | 3,965 |

Pass 1 is the single biggest lever in the repo: one file holding 26% of all
service code. It exceeds the per-pass budget on its own — run it alone, expect it
to be slow, and expect the altitude lens to carry it.

### Wave 2 — backend, remainder

| # | Pass | Scope | ~Lines |
|---|---|---|---|
| 5 | `studio` | `services/lora_test_studio.py`, `studio_scoring.py`, `studio_payload.py`, `studio_discovery.py`, `studio_storage.py`, `studio_lifecycle.py`, `studio_cells.py`, `studio_launch.py` | 3,280 |
| 6 | `routes` | `backend/app/routes/` + `utils/redact.py`, `utils/time.py` | 3,196 |
| 7 | `scrape` | `backend/app/scrape/` | 3,974 |
| 8 | `data-lifecycle` | `services/trash.py`, `integrity.py`, `curation_history.py`, `dataset_activity.py`, `background_jobs.py`, `updater.py` | 2,557 |
| 9 | `analysis-quality` | `services/image_processing.py`, `face_similarity.py`, `perceptual_hash.py`, `person_mask.py`, `watermark_lama.py`, `vision_ollama.py`, `ollama_control.py`, `joycaption.py`, `import_analysis.py`, `gpu_speed.py`, `utils/resolution.py` | 1,414 |

Pass 6 is the best altitude target in the repo — route handlers are where logic
that belonged in a service tends to settle. `datasets.py` (1,267) and
`training.py` (870) are two thirds of it.

### Wave 3 — frontend

| # | Pass | Scope | ~Lines |
|---|---|---|---|
| 10 | `dataset-components` | `frontend/src/components/dataset/` | ~7,500 |
| 11 | `hooks-utils` | `frontend/src/hooks/`, `utils/`, `api/`, `context/` | ~5,500 |
| 12 | `pages-shell` | `frontend/src/pages/`, `App.jsx`, `main.jsx` | ~2,600 |
| 13 | `remaining-components` | `frontend/src/components/` excluding `dataset/` | ~8,000 |

Pass 10 is oversized — `DatasetWorkspace.jsx` alone is 1,474 lines. Split it at
run time if the fan-out looks thin.

## Calibration

- **Reuse** is the highest-yield lens here. 48 service files and 123 components
  is exactly the scale at which the same helper gets written four times.
- **Efficiency** matters far more on this codebase than it did on the docs pass,
  which found nothing worth acting on. Image processing, training loops, and the
  in-process SQLite job dispatcher are where real waste will be.
- **Altitude** is the lens to trust on passes 1, 6, and 10 — the oversized files.
- Expect some passes to return nothing. That is a valid result, and reporting it
  honestly is worth more than a manufactured finding.

## Ledger

Update after every pass. `blocked` needs a reason.

| # | Pass | Status | Commit | Notes |
|---|---|---|---|---|
| 1 | face-dataset-service | done | `790fea8` | −47 net. Dead migration helper, fan-out check ×4, VLM text cleanup ×7, ref-parse ×2, dead dHash branches. Deferred: double image decode on import (needs sibling-module API change), caption-pipeline merge, coverage-state classifier. |
| 2 | lora-training-core | todo | — | |
| 3 | remote-training-publish | todo | — | |
| 4 | generation-engines | todo | — | |
| 5 | studio | todo | — | |
| 6 | routes | todo | — | |
| 7 | scrape | todo | — | |
| 8 | data-lifecycle | todo | — | |
| 9 | analysis-quality | todo | — | |
| 10 | dataset-components | todo | — | |
| 11 | hooks-utils | todo | — | |
| 12 | pages-shell | todo | — | |
| 13 | remaining-components | todo | — | |
