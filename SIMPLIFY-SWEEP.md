# Simplify sweep — standing goal

Paste the **Goal prompt** below into a session to run one pass. The ledger at the
bottom is the resume point, so a fresh session can pick up wherever the last one
stopped.

**Two run modes.** *One pass per session* is the default and the safe one — a
pass is a lot of verification, and a fresh context per pass is what keeps the
verification honest. *Continuous* runs passes back to back in one session until
the ledger is clear; use it when you want the whole sweep landed and are willing
to trade some per-pass scrutiny for it. Either way the per-pass protocol is
identical, and **every pass still gets its own commit, its own issue and its own
PR** — a pass that makes something worse must cost one `git revert` and one
closed PR, never an unpicking.

In continuous mode each pass branches off the *previous pass's* branch rather
than `main`, because every pass touches this file and `CHANGELOG.md`; branching
them all off `main` produces a queue of PRs that conflict with each other. The
stack merges in order and each PR's diff is only its own work.

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

For a **continuous** run, replace the last two lines of the first paragraph and
the "Do not start the next pass" sentence with: *work through every remaining
`todo` pass in ledger order without stopping, one commit / issue / PR per pass,
and report once at the end.* Everything else in the protocol is unchanged — in
particular, still capture a baseline per pass and still verify every finding
yourself.

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

Learned in pass 4.

- **`module.attr` access is a test seam. This is now the third pass it has
  bitten.** Pass 4 removed `hamming as _hamming` from `face_dataset_service` on
  a *green ruff F401* — and turned the gate red, because
  `test_dataset_import_from_scrape.py:65` reaches it as `svc._hamming`. Ruff
  cannot see through `module.attr`, so **F401 on a service module is a question,
  not a verdict**: grep the test tree for `<module>.<name>` before believing it.
  The import is back, with `# noqa: F401` naming the seam so the next reader
  does not repeat this. (Pass 1's lesson said to grep repo-wide; the new part is
  that a *linter* telling you it is dead does not discharge that.)
- **A dead symbol's docstring is usually lying about something else too.**
  Every one of the five listers/helpers deleted from `utils/comfyui.py` sat
  under a module docstring that described the app as having callers it does not
  have (`get_flux2_klein_models` "for klein_edit_helper", `apply_zimage_settings`
  "so the /generate route and the studio"). The prose drifts with the code and
  nothing tests prose. When you delete a symbol, re-read the paragraph above it.
- **Extract the algorithm, not the family.** The three trained-LoRA listers and
  the two LoRA-chain injectors each looked like three/two copies of a function;
  what was actually shared was the *entry shape* and the *chaining algorithm*,
  with the folder predicate and the node wiring legitimately different. Naming
  the shared part and passing the different part as data deleted 160 lines;
  merging the functions outright would have been rejected — and was, for
  `inject_sdxl_loras`, which also wires `clip` and discovers consumers by
  scanning.
- **The snapshot-before-mutate bug is the argument for the extraction.**
  `_chain_model_loras` snapshots its consumer list before inserting any node, so
  the first link is never repointed at itself. That subtlety existed in two
  copies; a fix landing in one would fail *silently* — the workflow still
  validates, the LoRA just never reaches the sampler. Duplication whose failure
  mode is silent beats duplication that is merely long.

Learned in pass 5.

- **A re-export block is two things wearing one coat.** `lora_test_studio`
  carried 30 `X = _scoring.X` aliases. Half are the module's contract — the
  sibling modules receive this module as `runtime` and reach `runtime.best_cell`,
  and tests monkeypatch `lts.get_krea_models` — and half were residue with zero
  readers anywhere. A reader cannot tell which is which without grepping all 30,
  so the block reads as "everything here is load-bearing" and nothing in it ever
  gets deleted. Verify the block *by name*, not as a unit: `runtime.<attr>` in
  the siblings plus `setattr(lts, ...)` in the tests is the complete list of what
  is contract. 17 of the 30 were dead.
- **When two copies exist, the docstring is on the wrong one.** `_wilson_lower_bound`
  existed twice; the copy with the 8-line explanation of *why* Wilson and not raw
  net had zero production callers, and the copy every ranking actually runs
  through had no docstring at all. That is the normal direction of this failure:
  prose gets written when a thing is introduced, and the *used* copy is the one
  that later gets moved. Before deleting a duplicate, check which copy is
  carrying the explanation — and move it, don't drop it.
- **Prose asserting an invariant is a request for a name.** `best_per_checkpoint`'s
  docstring said "MÊME tri Wilson que best_cell" — a four-tuple sort key restated
  by hand in two places, with a comment promising they agree. That promise is now
  `_ranked_positive_configs`. Pass 3 recorded this; pass 5 is the second sighting,
  which makes it a rule: a comment that says "same as X" marks a missing function.
- **An N+1 hides behind an optional parameter that already exists.**
  `_representative_image` re-queried every done image of the dataset once per
  checkpoint, on a 3-second poll — while the same module already had the fix as a
  convention (`scores=None`, "partageable … pour éviter de re-scanner la table").
  The fix was to follow the file's own established pattern, not to invent caching.
  When you find repeated work, check whether the module already names the way out.
- **The empty-pool policy is not part of the pool.** The base-model cascade was
  written four times, but the callers genuinely disagree on what an empty pool
  means: creation must refuse, resume must never raise mid-run. Extracting the
  rule and leaving the policy at the call site (`require=True`) unified four
  copies without flattening a real difference — the failure mode of getting this
  wrong is a resumed Krea cell silently re-rendering on a different base.
- **Line count is the wrong metric for a rule stated many times.** Pass 6's
  `_ok_or_404` saves nothing at any call site — one line before, one line after —
  and *adds* the helper's own lines. It was still right to extract: the rule
  "a missing resource is a 404 whose body is `{'error': 'not found'}`" was
  restated 19 times with no name. Codex was asked precisely because the
  arithmetic and the altitude disagreed, and its verdict was "duplicated policy,
  not duplicated syntax". When a pass finds a one-liner repeated at scale, count
  the rules, not the lines.
- **Naming the common case makes the exceptions legible.** The same pass found
  two sites that look identical to those 19 and are not:
  `dataset_lora_test_prompt_reorder` returns a 400 `'invalid'`, and
  `dataset_training_feedback` tests `payload is not None` where the helper tests
  truthiness (an empty-dict payload would flip from 200 to 404). Both were left
  written out in full. Before the extraction they were invisible in a field of
  identical lines; after it they are the only two that don't call the helper.
- **A user-visible string is behaviour.** The reuse lens's strongest-looking find
  was three hand-rolled copies of `_json_bool` sitting in the same file as the
  helper. Verification killed it: the helper raises `'{name}' must be a boolean`
  (quoted), while the copies say `rescue_small must be a boolean` and
  `include_albums must be a boolean.` — unquoted, one with a trailing period.
  Only one of the three matched, and reusing the helper there turns 3 lines into
  4. A finding that is right about the shape can still be wrong about the text.

### Carried-over findings

Real, verified, deferred because they fell outside their pass's scope. Fold each
into the pass named, rather than rediscovering it.

- **Verified in pass 6 and deliberately skipped.** The four traps below are the
  valuable half of the pass: each is a pair that a reuse-minded reviewer will keep
  re-finding, and each must stay split.
  - **GET-arg vs POST-body `base_model` resolution** (`training.py:267-272`,
    `:302-306`, `:327-331` vs `:110-114`, `:150-154`, `:205-209`, `:606-609` and
    the ternary form at `:648`, `:668`, `:697`). The service defaults
    `base_model=_PERSISTED`; `''` is not "absent", it is the explicit choice "use
    the official base". Query strings can use `is None` because an empty
    `?base_model=` still yields `''`; JSON bodies cannot, because `None` means both
    "missing" and "present and null" — hence `'base_model' in d`. Unify these into
    one `.get(key) is None` helper and a user picking "Official" in
    `dataset_train_continue`/`enqueue`/`schedule` has that choice silently dropped
    in favour of the persisted custom base — the exact `jamais un reset muet` the
    comment at `training.py:78` says the code exists to prevent.
  - **`datasets.lora_test_run` vs `studio.studio_run` error mapping**
    (`datasets.py:1162-1168` vs `studio.py:107-118`). Studio handles a third case,
    `StudioPartialLaunch` → 503. A per-dataset run is atomic (one dataset, one
    family, nothing to partially launch); a comparison run fans out and can half
    succeed. Collapsing to the shorter one turns a real partial failure into a 500;
    collapsing to the longer one bolts an unreachable branch onto the atomic route
    and hides that a `StudioPartialLaunch` there would be a genuine bug.
  - **`_klein_missing_response` vs `_studio_missing_response`.** Both build a 409
    listing missing assets. Klein's *starts background downloads*; Studio's
    docstring explicitly refuses to, because its assets are large and
    licence-gated. Pass 6 collapsed the four Klein call sites into
    `_map_klein_error` but deliberately left it in `datasets.py` rather than
    beside `_map_error` in `_common.py`, so the side-effecting one cannot be
    reached by accident from a Studio route.
  - **`dataset_train_run_checkpoint_delete`'s gate** (`training.py:637-639`) reads
    `if gate and not capabilities.probe().get('cloud_training')` where a dozen
    neighbours read plain `if gate:`. It deletes local *or* cloud checkpoints, so a
    cloud-only install with no local ai-toolkit must still reach it. "Simplifying"
    it to match its neighbours 409-blocks cloud-only users from deleting their own
    cloud checkpoints.
  - Also skipped: the ~41 `if not svc.get_dataset(...): 404` preambles (a helper in
    this codebase's `gate = ...; if gate: return gate` idiom is 3 lines replacing 2,
    and several callers need the fetched row while most need only the boolean); the
    13 `except ValueError as e: return jsonify({'error': str(e)}), 400` copies
    (2 lines either way, and `datasets.py` has two competing 400-body shapes —
    `{'error'}` vs `{'ok': False, 'error'}` — so unifying them is a behaviour
    decision, not a sweep edit); and the two crop-box coercions
    (`dataset_ref_crop:287-291` wraps the *service call* in the same `try` as the
    `int()` casts, so narrowing it to match `dataset_image_crop` would change which
    exceptions surface as `'invalid crop box'`).
- **Verified in pass 5 and deliberately skipped.** Each was confirmed against the
  code and left alone on purpose:
  - `studio_scoring.TEST_ASPECTS` (a set) vs `lora_test_studio.TEST_ASPECTS` (a
    dict) — a real hand-copy, but `lora_test_studio` imports `studio_scoring`, so
    the set is a deliberate import-cycle break. Unifying it means moving the dict
    down into `studio_discovery`, which is a structural move, not a sweep edit.
  - `_ci_join_exists` vs `studio_discovery.resolve_lora_path` — same
    case-insensitive path walk, different *security* contract: the resolver
    rejects `..`, enforces `commonpath` containment and requires a file; the probe
    deliberately accepts directories because its input is workflow-internal.
    Merging drops a traversal guard.
  - `_extra_lora_strength` (raises) vs the parse inside
    `apply_krea_lora_test_settings` (falls back to 1.0) — different *stages*:
    admission of user input must 400, workflow assembly of already-admitted or
    persisted values must not fail an otherwise recoverable resume.
  - The three parses of `row.extra_loras` — their post-conditions differ on the
    `batch` key, and `_normalized_extra_loras` keeping it is what makes a batch
    cell a distinct config from its reference cell. One shared parser that
    stripped `batch` would collapse the ⚖ axis in every score and ranking.
  - `lora_net_scores` sorting by raw net while `model_comparison` sorts by Wilson
    — intentional: within one run `launch_matrix` gives every subject an identical
    axis product, so sample sizes are equal by construction; across runs they are
    not.
  - `active_run_count()` global vs `active_run_count(dataset_id)` scoped — the
    asymmetry is the admission rule (a multi-LoRA comparison spans datasets, so it
    holds the whole studio), not an oversight.
  - The unreachable `run_owned` guards in `studio_lifecycle` — `run_owned` is a
    deliberate single-user no-op and its call sites are the single place a
    multi-user check would land. Deleting them saves 4 lines and removes the hook.
  - The three `Protocol` classes and the three `sys.modules[__name__]` names —
    internal-API shape and cosmetics respectively; neither is a simplification.
  - `init_image` / `denoise` are structurally always `None` downstream of
    `_sanitize_gen_knobs`, but the columns are schema and `set_best_settings` can
    still receive them from a client `generation_config`.

- **Pass 6 (`routes`) or `/code-review`: `studio_payload_run` renders one LoRA
  under two different names in one response.** `loras[].lora_label`
  (`studio_payload.py:237`) is the bare basename while `lora_ranking[].lora_label`
  (`:208`) is the formatted label, so the same LoRA reads
  `lora_Lola2_000004000_bigLove_zt3` in the column header and
  `Lola2 · 4000 steps · bigLove zt3` in the ranking panel of the same view
  (`LoraComparisonGrid.jsx:50` vs `LoraRankingPanel.jsx:32`). Same split at `:246`
  vs `:121`. Fixing it changes user-visible strings, which is why the sweep left
  it: it is a behaviour change, not a simplification.
- **`/code-review`: `_extra_lora_strength` rejects negative strengths that the
  rest of the stack accepts.** The UI slider (`ZImageLoraConfig.jsx:17-23`) and
  `inject_zimage_loras` both allow negative LoRA weights; the studio's admission
  clamp rejects `< 0.0` with a 400, so a config the user can build in Generate
  cannot be tested in the Studio.
- **`/code-review`: `_record_for_checkpoint` lowercases `family` while its caller
  keys `by_scope` on the raw `record.family`.** A record stored with a
  non-lowercase family would be silently dropped by the re-filter at
  `studio_scoring.py:142-143`. Either the store guarantees lowercase (and the
  filter is dead) or it does not (and this drops evidence) — it cannot be both.
- **Efficiency, outside pass 5's file set: `fetch_object_info_classes` is an
  uncached multi-MB HTTP GET run once per launched cell.** `preflight_family` is
  correctly called per cell (resume has no run-level preflight, so deleting it
  would un-guard resume), but the *probe* should be memoized per launch. The fix
  belongs in `utils/comfyui.py`, which pass 5 did not own.
- **Efficiency, ~~pass 6 (`routes`)~~ → a services pass: `studio_run_history` is a
  2-query N+1 over up to 81 candidate runs**, hydrating every row of each run only
  to take `len()`. Two aggregates would do. Not on the poll path, hence deferred.
  *Re-filed by pass 6:* the code is `services/studio_payload.py:160`, not a route —
  `datasets.py:1128` only calls it. The original pass-6 assignment was a misfile.
- **Efficiency, outside pass 6's file set: the three LoRA listers have no cache,
  and `studio_payload` calls them ~5× per poll tick.** `get_zimage_loras` /
  `get_sdxl_loras` / `get_krea_loras` (`utils/comfyui.py:1052-1124`) each do a full
  `os.walk` of `models/loras` with no caching, while their sibling *base-model*
  listers in the same file already share a 5-minute TTL cache (`_MODEL_CACHE_TTL`)
  — the asymmetry reads as an oversight. Per tick of `studio_payload`:
  `available_families` walks the tree once per family (3), then
  `list_test_checkpoints` (1) and `permanent_lora_candidates` (1) walk it again.
  `/api/dataset/<id>/lora-test/status` is polled every 3000ms
  (`useLoraTestStudio.js`) for as long as any grid run has pending cells, so this
  is the hottest sustained poll in the app. The fix is the TTL cache the file
  already has, plus de-duplicating the same-family calls within one payload build.
  Belongs to a `utils/comfyui.py` + `studio_discovery.py` pass, which pass 6 did
  not own. (`list_all_testable_checkpoints` shares the pattern but is mount-time
  only, so it inherits the fix for free.)
- **Efficiency, pass 10-13 (frontend): `useDataset.refresh()` re-fetches the whole
  image window from `cursor=null` on every SSE `dataset` event.** The
  `?include_images=0` half of the same call is already revision-cached server-side
  (`_DATASET_AGGREGATE_CACHE`), so "SSE change → cheap refetch" was the design and
  only the image half was left out of it. Bounded to 1/sec by the SSE loop, but
  during a batch job the revision changes nearly every tick, so a fully-loaded
  large dataset re-issues `ceil(N/100)` page queries per second for the job's
  duration.
- **Pass 15 or a light-constants pass: `settings.py:231` hand-writes
  `{'klein', 'nanobanana', 'chatgpt'}`** where `datasets.py:400` correctly uses
  `{'klein', *svc.API_ENGINES}`. Add an engine to `API_ENGINES` and the settings
  validator silently keeps rejecting it. Not fixed in pass 6: `settings.py` imports
  `face_dataset_service` only lazily inside functions, and making it pay that
  import at every settings write to read a 2-tuple is a worse trade than the
  duplication. The real fix is moving `API_ENGINES` to a light shared constants
  module — the same shape as pass 15's family-label migration, and outside pass 6.

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
  others say `Krea 2`. Pass 6 found a SIXTH copy:
  `routes/_common._STUDIO_FAMILY_LABELS` (`_common.py:43`), which is the one
  users see in the Studio's missing-assets and arch-mismatch 409 banners — and it
  is on the `Krea 2 Turbo` side of the split. Add it to this pass's migration
  list; the banner text is user-visible, so it is also the strongest argument
  that the label question needs answering rather than deferring. Codex and I agreed to defer: importing from
  `utils/comfyui` inverts the dependency direction (it pulls in `requests`,
  `subprocess`, `flask`, config), and picking the surviving label is a product
  decision, not a refactor. Give it a small pass that adds a neutral
  `training_families.py` and migrates all five consumers at once — the same
  shape as the `file-hashing` pass.
- ~~Pass 3: N+1 registry query per checkpoint.~~ **Done in pass 3**
  (`checkpoint_registry.mtime_resolver`).
- **`/code-review`, correctness: the caption cleaner and the caption *detector*
  disagree.** `face_variations._DROP_SENT` only matches `skin\s+(?:tone|texture)`
  and carries no eye-colour or face-shape pattern, while `_IDENTITY_LEAK` (used
  by `caption_has_identity_leak`) matches more. A caption can therefore survive
  cleaning and still be judged a leak — and `lora_training.py:1618` uses that
  judgement to *drop rows from training*. Deriving one regex from the other
  changes which captions get cleaned, so it is not a sweep finding.
- **`/code-review`, correctness: three modules disagree on the ComfyUI
  model-reference separator.** Checkpoints are referenced with `/`, unet and
  lora with `\`, and `resolve_klein_unet` uses `os.sep`. They agree today only
  because ComfyUI normalises; the third form is the one that changes meaning
  across platforms. Related: `zimage_convert._resolve_merge` only finds its file
  through the basename fallback on POSIX.
- **`/code-review`, minor: `chatgpt_image._generate_via_subscription` reuses the
  local name `body`** for the request payload (line 193) and the response text
  (line 240). Safe only because the 401 retry branch `continue`s before the
  second binding is read — one edit away from being a real bug.

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

Verified in pass 4 and deliberately **skipped**, for the same reason.

- Unifying the two models-root derivations (`_out_dir()` + `../models` vs
  `cfg.comfyui_dir('models')`) and deleting `_out_dir()`: **Codex consensus to
  defer.** The two genuinely resolve differently when the config carries an
  override, so this is a correctness fix that needs its own targeted tests, not
  a dedup.
- `enqueue_klein_edit` resolving Klein assets twice: `klein_missing_assets` is a
  test seam — `test_image_improve.py` monkeypatches it as a *zero-argument*
  lambda at six sites, so neither bypassing it nor giving it parameters is safe.
- A `_BY_LABEL` index over the variation catalog: nets ≈ 0 lines, and a 63-item
  scan is nothing beside generating the image it precedes (altitude).
- The unreachable trailing `return None` in `nanobanana.py:90` and
  `chatgpt_image.py:253`: one line each, and the explicit terminator documents
  the None-on-failure contract for a future third retry branch.
- `chatgpt_image.pinned_lane()`, `_MODEL_SUFFIXES`, `NSFW_LABEL_PREFIX`: each
  needs edits well outside the pass, or is trivial, or wants a test rather than
  an extraction.
- `check_comfyui_status`: dead but for its own test. Deleting a *tested* public
  health accessor is churn, not simplification.
- `chatgpt_oauth`'s double `_load()` per subscription request: tiny file, and
  merging the two reads changes the locking shape.
- Merging `get_zimage_models` / `get_krea_models`, folding `inject_sdxl_loras`
  into the shared chainer, and putting `_coverage_metadata` on `_e()`: all three
  rejected by altitude as shape-matching without a shared rule.

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

### Wave 4 — cross-cutting

These are not file groups. Each is a single duplication that spans several passes,
so no pass owns it; each was found and deliberately deferred by the pass that hit
it first. Run them last, when every consumer is known.

| # | Pass | Scope | Origin |
|---|---|---|---|
| 14 | `file-hashing` | one shared chunked-SHA-256 helper; delete the five copies in `lora_training_export`, `training_snapshot`, `checkpoint_registry`, `cloud_training`, `backend/infer/lama_model` | passes 2, 3 |
| 15 | `training-families` | one neutral `services/training_families.py`; migrate `lora_training._FAMILY_LABEL`, `run_share`, `hf_publish`, `utils/comfyui.FAMILY_LABELS`, `routes/_common._STUDIO_FAMILY_LABELS` and the frontend copy | passes 3, 6 |

Pass 15 carries a product decision, not just a refactor: the copies have already
drifted (`Krea 2 Turbo` vs `Krea 2`) and someone must say which label is correct.
Surface that rather than picking silently.

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
| 4 | generation-engines | done | `0c58f5b` | −159 net. Five dead listers/helpers and 3 orphaned imports out of `utils/comfyui.py`; trained-LoRA picker entry ×3 → `_lora_entry`; LoRA-chain injector ×2 → `_chain_model_loras` (the snapshot-before-mutate subtlety now stated once); `zimage_convert` transformer-ready check ×2 and convert-state write ×5 → two helpers; identity-trait list ×3 → one constant; dead return value out of `apply_zimage_settings`; node 92 added to `_REQUIRED_NODES`. Three module docstrings corrected where they named callers this app does not have. Also cleared the repo's one standing `ruff` error (pass 1's own residue) — as a `noqa`, because it is a test seam. Deferred: models-root unification (Codex: needs correctness tests), caption cleaner/detector regex divergence. |
| 5 | studio | done | 4b9ee14 | 17 dead re-export aliases + 2 dead frontend-mirror constants + `model_net_scores` deleted; the base-model pool, permanent-LoRA validation, Krea rebalance encoding and shared-seed series extracted once each and shared by `create_run`/`create_comparison_run`/resume; `_wilson_lower_bound` and `_basename` collapsed to aliases with the docstring moved onto the live copy; `_ranked_positive_configs` names the sort `best_cell`/`best_per_checkpoint` both restated; `_tally_vote` names "only ±1 is a vote" (5 sites); `_representative_image` N+1 and the `_record_for_checkpoint` per-row filesystem resolve fixed; `list_all_testable_checkpoints` double scan removed. 10 skips and 5 carried findings recorded above. Gate 1740 passed / 1 skipped, ruff clean. |
| 6 | routes | done | `809669e` | +33 net (the helpers' own docstrings, which state the deduped rules). `_ok_or_404`/`_payload_or_404` name the "not found is a 404 with `{'error': 'not found'}`" contract that was restated at 19 sites across 2 blueprints — 2 look-alike sites deliberately left written out, and now visible as the only exceptions. `_map_klein_error` collapses the Klein-missing branch + its inline import from 4 handlers (kept in `datasets.py`, not `_common.py`: it starts downloads, which the Studio 409 refuses). `_head_crop_warning` names the guard-rail rule with both CTAs left caller-supplied, since the two user-visible strings had drifted and must stay drifted. `_probe_outbound_ip` shares the UDP-connect socket lifecycle between `_lan_ip`/`_tailscale_ip` with each probe's filter left at the caller. 5 redundant local re-imports of module-level names dropped; `dataset_train_checkpoints` no longer runs `get_dataset` twice per request. 4 traps + 3 skips and 4 carried findings recorded above; the efficiency lens found nothing inside this pass's file set. Gate 1740 passed / 1 skipped, ruff clean. |
| 7 | scrape | todo | — | |
| 8 | data-lifecycle | todo | — | |
| 9 | analysis-quality | todo | — | |
| 10 | dataset-components | todo | — | |
| 11 | hooks-utils | todo | — | |
| 12 | pages-shell | todo | — | |
| 13 | remaining-components | todo | — | |
| 14 | file-hashing | todo | — | |
| 15 | training-families | todo | — | |
