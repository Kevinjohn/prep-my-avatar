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

Learned in pass 2.

- **Import order is the constraint that governs cross-module dedup.**
  `lora_training.py` imports its own carved-out siblings *mid-file* (settings
  @698, export @1105, config_builder @1120, checkpoints @1129, process @1913,
  queue @2197) and ends with an `__all__` facade re-exporting everything. A
  sibling can only `from .lora_training import X` when `X` is defined *above*
  that sibling's own import line; anything defined later must be reached at call
  time as `training.X`. Pass 2's reuse lens proposed a top-level import that
  would have raised `ImportError` at startup. Check the line number of the
  definition against the line number of the import before moving any name.
- **Where to put a new shared helper is decided by its callers' import lines,**
  not by what reads well. `_effective_vae_te` had to sit near the top of
  `lora_training.py` so that both process (@1913) and queue (@2197) could import
  it eagerly.
- **`training.X` attribute access is a test seam, not an oversight.** Several
  tests monkeypatch through the module object. Converting `training.X` into a
  direct `from … import X` silently breaks patching without failing at import.
- **A second module-level assignment makes the first one dead.** Pass 2 found a
  `_FAMILY_LABEL` dict declared twice ~900 lines apart; function bodies resolve
  globals at call time, so only the later one was ever read. Two definitions of
  the same module-level name are always a finding.
- **Re-doing work is not always waste.** The efficiency lens flagged
  `training_snapshot.capture` hashing each source twice; the second pass is a
  documented re-verification after the whole copy window, because a file copied
  early can be edited while later files copy. Read the comment before deleting
  the second call.

Learned in pass 3.

- **Fan the lenses out BEFORE you start editing.** Pass 3 began applying early
  findings while the altitude lens was still reading, and it reported "another
  session has been editing these files concurrently" — it was seeing this
  session's own working tree. The lenses read the tree, not a snapshot; a moving
  tree produces confusing and occasionally alarming findings.
- **When two lenses disagree, the one arguing *against* the extraction is
  usually right.** Reuse proposed a `_hub_header` extraction and a shared
  staging-scan helper; altitude showed each would add about as many lines as it
  removed, and that the two staging scans sort on different keys. Both were cut
  to the part that was genuinely one rule (a single regex constant). Reuse
  optimises for "these look alike"; altitude asks whether there is a rule.
- **A duplicated guard is worth extracting even at zero line saving, when the
  two copies must agree by contract.** `gpu_tiers` and `launch_cloud_training`
  each refused the same local-only families, and each derived the same offer
  filters; a drift there means the picker offers a GPU class the launch then
  rejects. The comment in `gpu_tiers` already asserted the invariant in prose —
  that prose is the signal the rule wants a name.
- **A guarded parse and an unguarded parse of the same field are not
  duplicates.** `cloud_training` reads `train_params` at eleven sites: five had
  a try/except+isinstance guard (deduped into `_run_params`), six deliberately
  do not. Converting the unguarded six would have silently swallowed corruption
  they currently surface. Check what each copy does on the error path before
  calling them the same code.
- **A shared helper can add a query that no caller previously made.** Batching
  `record_for_mtime` into a `mtime_resolver` moved the query to the top of the
  loop — which meant an empty checkpoint folder gained a query it never made
  before, and `backfill_legacy_baselines` calls `list_checkpoints` per dataset ×
  per train type precisely to test emptiness. The early return is part of the
  fix, not tidying.
- **Ask Codex when the choice is a product decision in disguise.** Twice in
  pass 3 the technical argument was settled and the remaining question was not
  (which of two drifted family labels is correct; whether an endpoint's
  freshness contract may change). Both were deferred by consensus, correctly.

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
- **Its own pass (`file-hashing`): chunked SHA-256 is written five times.**
  `lora_training_export._sha256_file`, `training_snapshot._sha256`,
  `checkpoint_registry._file_hash`, `cloud_training._file_sha256` and
  `backend/infer/lama_model._sha256` are the same open-loop-digest with
  different chunk sizes. It spans passes 2, 3 and 9, so no single pass owns it;
  give it a small pass that adds one shared helper and deletes the other four.
- **Its own pass (`training-families`): the family-label map is written five
  times, and has already drifted.** Pass 2 logged this as pass 3's, but pass 3
  found it larger than recorded: `lora_training._FAMILY_LABEL`,
  `run_share.py:31`, `hf_publish.py:45`, `utils/comfyui.FAMILY_LABELS` and the
  frontend each carry a copy, and one already says `Krea 2 Turbo` where the
  others say `Krea 2`. Codex and I agreed to defer: importing from
  `utils/comfyui` inverts the dependency direction (it pulls in `requests`,
  `subprocess`, `flask`, config), and picking the surviving label is a product
  decision, not a refactor. Give it a small pass that adds a neutral
  `training_families.py` and migrates all five consumers at once — the same
  shape as the `file-hashing` pass.
- ~~Pass 3: N+1 registry query per checkpoint.~~ **Done in pass 3**
  (`checkpoint_registry.mtime_resolver`).

Verified in pass 2 and deliberately **skipped** — recorded so they are not
rediscovered and re-argued. Each fails a non-negotiable rather than being wrong.

- Moving the ~185 lines of train-settings vocabulary and validators out of
  `lora_training.py` into `lora_training_settings.py`: architectural, and
  deletes nothing.
- Splitting the 435-line `training_preflight` into `_rule_*` functions: adds
  abstraction, removes zero lines.
- `imported_checkpoint_path` derived in both `dataset_disk_usage` and
  `delete_imported_checkpoint`: medium confidence, and the second is a
  destructive path.
- The `training_folder` ternary repeated 5× in `lora_training_config_builder`:
  nets −2 lines.
- The 8 `_x_eff` getters sharing a lookup shape: marginal, low agent confidence.

Verified in pass 3 and deliberately **skipped**, for the same reason.

- Memoizing `checkpoint_registry._file_hash` on `(path, size, mtime_ns)` in
  `dataset_state`: Codex consensus to defer, with a decisive disproof —
  `test_manifest_hashes_exact_bytes_not_size_or_mtime` already covers a
  same-size/same-mtime content replacement, which that cache key would miss. It
  is a real performance problem, but the fix redefines what the endpoint
  promises, so it needs its own change.
- `_register_instance` recomputing `estimated_minutes` / `estimated_cost_usd`
  after `_assert_projected_budget` already persisted them: genuinely redundant,
  but removing it flips `estimated_cost_usd` from `None` to `0.0` for unpriced
  offers — a persisted-field change in a billing path.
- Routing `_download_intermediates` through `_fetch_checkpoint`: behaviour
  change (short files would be deleted rather than left). The missing truncation
  guard it exposes is a correctness gap and belongs to `/code-review`.
- `fds._safe_json` re-implemented ~10× across `run_share`, `cloud_training` and
  `checkpoint_registry`: the copies have drifted (`all_runs` lacks the
  `isinstance` guard the Share-config renderer has), so unifying them decides a
  semantic question rather than deleting a duplicate.
- Throttling the per-poll `training.log` rewrite + fsync: the only cheap test is
  the heuristic "equal length implies equal content", on a durability path.
- Moving vast's `-p <port>` env-key encoding into `vast_client`: relocates the
  knowledge rather than deleting it.
- `_remote_basename` (4 one-liners), the `_hub_header` scalar keys, a shared
  staging-scan helper, and `hf_publish`'s `_jobs` / `_lock` in-memory mirror
  (architectural). All net roughly zero lines or exceed the pass.

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
| 2 | lora-training-core | done | `b7e2143` | −18 net. Dead second `_FAMILY_LABEL`, `_trigger_boundary` and `_pid_alive` copies, ai-toolkit arch probe ×2, VAE/TE override rule ×2 (had drifted), queue launch block ×2, family dispatch ×4, dead store. Preflight now reads the stored dHash instead of re-decoding every image. Deferred: shared SHA-256 helper, checkpoint N+1, `_FAMILY_LABEL` in run_share/hf_publish. |
| 3 | remote-training-publish | done | `b741725` | +33 net (docstrings that state the deduped invariants). Offer filters ×2 and local-only-family guard ×2 (picker vs launch — must agree by contract), Retry/Continue relaunch ×2, publish staleness signature ×2, JSON-object response contract ×4 (vast) and ×2 (ai-toolkit), remote "already started" status set ×3, step-suffix regex ×4, `train_params` guarded parse ×5, legacy fingerprint rule ×2, `error_pod_kept` query ×2, `_dataset_name` in terms of `_dataset_names`, dead `reconcile_orphans(wait=)`. Efficiency: checkpoint N+1 fixed via `mtime_resolver`, plus 3 double-derivations. Deferred: family labels (own pass), `_file_hash` memoization, `_safe_json` ×10. |
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
