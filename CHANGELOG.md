# Changelog

All notable changes to Prep My Avatar are documented in this file.

The project uses calendar versions in the form `YYYY.MM.DD.N`. Changes remain
under **Unreleased** until a release is tagged.

## Unreleased

### Changed

- The API's "not found" contract is now written once instead of nineteen times.
  Every route that answered a missing dataset, image or run with a 404 spelled
  out the same status-and-body pair by hand; that rule now lives in two named
  helpers. Two routes that look identical but are not — one answers 400 for an
  invalid reorder, one distinguishes an empty result from a missing one — are
  still written out in full, and are now the only two that stand out.
- Listing a dataset's checkpoints no longer looks the dataset up twice in the
  same request.
- The "auto head-crop didn't run" warning is now chosen in one place. Both the
  reference upload and the re-crop decide the message the same way — is the
  Ollama vision model ready, or was no face found — while keeping their own
  wording, which differs between the two screens and is unchanged here.
- Training preflight no longer re-decodes every admitted image to find
  near-duplicates. It reads the stored `perceptual_hash` that the import
  already wrote from the same normalized bytes, and falls back to decoding only
  when that column is empty. Preflight runs on tab open, on every launch and on
  every queue admission, so this removes a full Pillow decode per kept image
  from all three.
- Listing a dataset's checkpoints now loads that dataset's training-run records
  once for the whole folder instead of re-running the same query for every
  checkpoint file. A folder of N checkpoints previously cost N identical
  queries; the annotations themselves are unchanged, and a folder with no
  checkpoints now makes no query at all.
- The LoRA Test Studio's poll no longer re-reads the whole image table once per
  checkpoint. Choosing the representative image for each checkpoint's best
  config re-loaded every finished image of the dataset on each pass; it now
  loads them once for the whole list. Attributing images to the training run
  that produced them likewise resolved a path on disk and read its mtime for
  every image row, and now does so once per distinct dataset/family/checkpoint.
- Listing every testable checkpoint across datasets now walks the LoRA folder
  once per family instead of twice. The listing previously asked which families
  had checkpoints, then re-scanned each of those families to get the same list
  back.

### Fixed

- The queue and the launcher now apply one shared rule for SDXL-only VAE /
  text-encoder overrides, instead of two hand-synchronised copies, so the queue
  cannot admit a job the launcher would later refuse.

### Internal

- The LoRA Test Studio coordinator no longer re-states the rules its two launch
  paths share. Building the pool of base models for a family, validating
  always-on LoRAs, encoding the Krea rebalance value and deriving a run's shared
  seeds each existed as a hand-copied block in both `create_run` and
  `create_comparison_run` — and the base-model pool in the resume path as well,
  making four copies of a rule the three paths must agree on: if resume lost the
  leading `None` that means "the UNET wired into the workflow", a legacy Krea
  cell would silently resume onto a different base. Each rule now has one
  definition. The differences that are real are preserved: creation refuses an
  empty pool while resume falls back and never raises mid-run, and the two
  `create_*` functions stay separate because they derive the family, handle the
  base axis and scope the LoRA whitelist differently.
- The Wilson ranking metric and the LoRA-path basename helper existed twice
  each. Both are now single definitions aliased from the module that owns them,
  and the explanation of why rankings use a Wilson lower bound rather than a raw
  like count moved from the copy nothing called onto the copy every ranking
  runs through.
- The sort behind "recommended config" is now written once. `best_cell` and
  `best_per_checkpoint` each restated the same candidate filter, neutral-model
  default and four-part sort key, with a comment in one promising it matched the
  other; both now call `_ranked_positive_configs`. The rule that only 👍/👎 count
  as votes — and that an unrated image inflates neither — is likewise named
  once and used at the five places that were incrementing the same three
  counters by hand.
- Removed 17 module-level re-export aliases, two frontend-mirror constants and
  the `model_net_scores` function from the Studio coordinator, all verified to
  have no reader in the backend, the tests or the frontend. The aliases that
  remain are the ones the sibling modules and the test seams actually reach, so
  the block now describes the module's contract instead of burying it in
  residue. The module docstring, which described a migration from another
  project and named symbols this app does not have, now describes the module.


- Removed a dead second definition of the training family-label table, a
  duplicated trigger-boundary rule, a duplicated PID-liveness helper, a
  duplicated ai-toolkit arch probe, a duplicated queue-launch block, and a dead
  store in the queue advance path. No behaviour change.
- Cloud training, the vast.ai and ai-toolkit clients, Hugging Face publishing
  and the run registry now each state their shared rules once instead of
  repeating them. The GPU-tier picker and the launch derive their offer filters
  and their local-only-family refusal from the same helpers, so the picker can
  no longer offer something the launch would reject; Retry and Continue share
  one relaunch path, so a training parameter cannot be preserved by one and
  dropped by the other; the publish staleness check derives both of its
  snapshots from one field list; and the ai-toolkit "already started" status
  vocabulary, the checkpoint step-suffix pattern, the `train_params` parse rule,
  the JSON-object response contract and the legacy-fingerprint compatibility
  rule each exist in one place. Also removed an unused `reconcile_orphans`
  parameter and stopped recomputing three per-request values that were being
  derived twice. No behaviour change.
- Trimmed the ComfyUI helper down to what this app actually calls. Five listers
  and helpers inherited from the parent project — video/other-app LoRA listers,
  a duplicate checkpoint lister, a webhook-notify configurator, a Klein model
  lister the Klein path does not use, and an Ollama lifecycle trio superseded by
  `ollama_control` — had no caller here and are gone, along with the imports
  they held open. Three module docstrings that described callers this app does
  not have were corrected rather than left to mislead the next reader.
- The three trained-LoRA pickers (Z-Image, SDXL, Krea) now build their entries
  through one helper, so the picker's filename form, label fallback and trigger
  convention are stated once and the next family lister inherits the fixes
  instead of the drift. Only the folder predicate differs between them, and it
  stays local to each.
- The Krea and Z-Image LoRA-chain injectors now share one chaining routine,
  parameterised by which node loads the UNET, which nodes consume its model, and
  the strength bounds. The part worth stating once is that the consumer list is
  snapshotted before any node is inserted, so the head of the chain is never
  repointed at itself — a fix to that in only one copy would have failed
  silently, with the workflow still validating and the LoRA simply never
  reaching the sampler. The SDXL injector is deliberately left alone: it wires
  `clip` as well as `model` and finds its consumers by scanning.
- Z-Image conversion now asks "is this transformer usable?" and writes its
  progress state through one helper each, instead of five near-copies. The two
  ends of the conversion have to agree by contract — a stricter rule at one end
  would silently re-convert a 12 GB model on every launch, a looser one would
  train against a truncated transformer — and the poll state's key and TTL are
  now stated once. Also dropped a return value from the Z-Image workflow helper
  that only the parent project's `/generate` history logging consumed; the one
  caller here discarded it.
- The face-variation prompts now interpolate one shared identity-trait clause
  across their three wrappers instead of repeating it, so a trait added for one
  engine cannot go missing for another — a divergence that fails nowhere and
  just trains a LoRA on a face that drifts. Prompt text is byte-identical.
  Separately, the Klein edit workflow's required-node list now includes the
  positive `ReferenceLatent` node the multi-reference chain anchors to
  unconditionally, so a workflow missing it fails at validation with a clear
  message rather than further downstream.

## 2026.07.28.2

### Release highlights

- Published a patch release of the repository-wide reliability and recovery
  hardening delivered in `2026.07.28.1`; there are no additional functional
  changes in this patch.

## 2026.07.28.1

### Release highlights

- Completed a repository-wide correctness and reliability hardening pass across
  dataset preparation, local and cloud training, Studio, installers, updates,
  recovery, packaging, and the responsive frontend.
- Made destructive filesystem and database operations transactional or
  recoverable, including contained exports, dataset Trash, immutable training
  snapshots, durable queue ownership, update rollback, and verified
  pre-migration database restoration.
- Added exact restart handoff and recovery contracts, deterministic inference
  provenance, cloud billing safeguards, typed and redacted API failures, and
  durable installer cancellation and environment repair.
- Expanded automated coverage to include historical database upgrades,
  concurrency and crash windows, every scraper adapter, mounted frontend
  workflows, accessibility, desktop/mobile E2E behavior, packaging, and release
  publication fault recovery.

### Cross-platform reliability and CI

- Fixed Python 3.10 ZIP imports from Flask/Werkzeug multipart uploads. Legacy
  spooled streams that implement `read`, `seek`, and `tell` but lack the newer
  `seekable` method are now adapted without buffering large archives in memory.
- Standardized persisted uploaded-original paths to portable POSIX-style
  identifiers so backups created on Windows restore correctly on Linux or
  macOS, while host-native paths continue to be used for filesystem access.
- Restored the missing run-comparison component to source control after a broad
  runtime-data ignore rule accidentally excluded its directory. Frontend builds
  and Playwright checks now reach and exercise the complete application again.
- Made cloud-resume, portable-launcher, and process-lock tests respect native
  Windows path and mandatory byte-lock semantics instead of assuming POSIX path
  separators or reopening an actively locked file.
- Isolated the cloud admission race test from the shared in-memory SQLite
  connection used by the test harness. The test still exercises the real
  admission critical section without introducing unsupported concurrent reads
  on one Windows SQLite connection.
- Made successful optional-ML installer and updater tests explicitly model a
  supported feature interpreter. Python 3.10 continues to support the core app
  while correctly refusing the reviewed Python 3.11–3.12 ML dependency graph.
- Added regression coverage for Python 3.10 upload streams, portable provenance
  paths, native checkpoint paths, Windows launcher commands, lock ownership,
  optional dependency updates, and concurrent cloud admission.

### Dataset workflow and recovery

- Added app-wide, recoverable Trash handling for datasets, individual images,
  checkpoints, deployed LoRAs, cloud staging data, regenerated image versions,
  and failed training-launch inputs. Permanent deletion is now an explicit
  **Empty trash** action.
- Added curation history and undo support so recent keep/reject decisions can be
  reversed without rebuilding the dataset.
- Added a read-only integrity report covering SQLite consistency, relationship
  validity, missing referenced files, unsafe links, and untracked dataset files.
- Expanded portable dataset backups to preserve exact uploaded originals,
  analysis, source rights, anchor decisions, coverage state, training settings,
  image relationships, watermark state, and generation provenance.
- Hardened backup import with archive size/count limits, path validation,
  collision detection, relationship remapping, prefix-aware payload validation,
  and cleanup of partially restored datasets.
- Made dataset deletion transactional across the database, portable backup, and
  raw dataset folder. Failed snapshots no longer leave temporary archives, and
  late generation callbacks cannot recreate a deleted dataset directory.
- Fixed restore cleanup so a stale backup file cannot prevent the successfully
  restored Trash entry from being consumed.

### Training snapshots and feedback

- Added immutable per-launch training snapshots. Admitted images and settings
  are copied to a private staging directory, hashed, recorded in a manifest,
  and atomically published only if the source dataset revision remains stable.
- Linked local and cloud launches, checkpoints, Studio results, fixed seeds,
  votes, and selected best settings through persistent training-run records.
- Added a training feedback panel that summarizes evidence by run and recommends
  whether to preserve a recipe, compare another checkpoint/strength, or revise
  the dataset.
- Added source-rights and identifiable-person consent checks to training
  preflight, plus a separate publishing-rights confirmation for Hugging Face.
- Preserved the exact base model, variant, VAE/text-encoder overrides, settings,
  manifest, and preflight decisions used by each launch.
- Made failed local launches roll back provenance, archived runs, rotated logs,
  queue state, configuration files, and partially materialized snapshots.
- Added safer cloud admission with live GPU offer tiers, runtime/cost estimates,
  concurrency and monthly-budget limits, host reliability controls, bounded
  readiness/stall/runtime timeouts, and resumable run monitoring.

### Generation, curation, and large datasets

- Made remote generation opt-in and kept local Klein generation available
  without remote-data consent. Excluded images remain outside provider anchor
  packs.
- Added durable background-job tracking and duplicate-work guards for long-lived
  request-spawned operations.
- Added paginated dataset-image loading while preserving whole-corpus summaries
  for navigation and readiness decisions.
- Made curation and caption review hydrate the complete corpus before enabling
  cross-image actions. Hydration now has an independent request lifecycle, so
  routine event-stream refreshes cannot cancel or truncate it.
- Improved corpus analysis, coverage policy, source-rights editing, duplicate
  detection, image-improvement review, small-image rescue, and watermark review.
- Prevented queued and API-backed generation completions from committing into a
  dataset after it has moved to Trash.

### Application reliability and updates

- Added a single-process data-directory lock for the server, launcher, updater,
  and recovery bootstrap so two app instances cannot run in-process schedulers
  against the same SQLite database.
- Split health reporting into liveness and readiness endpoints. Readiness checks
  the schema migration ledger, writable data storage, and committed frontend
  assets while retaining the legacy health endpoint for compatibility.
- Added structured API errors with stable error codes and request IDs.
- Reworked Git-checkout updates into fast-forward-only transactions with a
  private recovery journal, dependency snapshots, isolated startup checks,
  frontend verification, restart handoff, and rollback that preserves local
  edits.
- Improved Windows bootstrap and portable-launcher recovery, Python selection,
  dependency installation, process locking, and restart behavior.
- Added explicit configuration for ai-toolkit and optional ML worker interpreters
  so heavyweight dependencies can remain isolated from the core server runtime.

### Security and privacy

- Added access-token authentication for non-loopback/LAN deployments, including
  a dedicated remote-login flow. Tokens are no longer placed in URLs or QR-code
  query strings.
- Kept loopback access local and token-free while requiring an explicit opt-out
  before exposing an unauthenticated non-loopback server.
- Hardened outbound scraping and provider requests against unsafe redirects,
  private-address resolution, DNS rebinding, oversized responses, unexpected
  content types, and unsafe downloaded filenames.
- Tightened file handling across datasets, checkpoints, imports, publishing,
  update archives, and generated artifacts with containment and symlink checks.
- Pinned production, scraping, ML, build, and frontend dependency graphs and
  added production dependency-audit commands to the contribution workflow.

### Frontend and accessibility

- Reorganized the dataset workspace into clearer sections for images, sources,
  curation, captions, training, checkpoints, and Studio while preserving deep
  links and truthful capability-based navigation.
- Added accessible confirmation and cloud-launch dialogs with focus trapping,
  body-scroll locking, keyboard handling, and destructive-action focus rules.
- Improved responsive behavior, filtered-grid visibility, progress reporting,
  review affordances, recovery messaging, and partial-failure reporting when
  emptying Trash.
- Added a complete frontend quality gate: ESLint, JavaScript typechecking,
  contract tests, production build, and Playwright coverage for desktop/mobile
  flow, accessibility, dialog behavior, and horizontal overflow.

### Operations and documentation

- Added continuous-integration coverage for backend tests, frontend gates,
  dependency audits, and release validation.
- Updated Docker defaults, health checks, examples, and documentation for the
  authenticated LAN-access model.
- Added contributor instructions for the pinned development requirements,
  optional ML environments, frontend quality gate, audits, and E2E suite.
- Expanded the user guide with immutable training snapshots, feedback evidence,
  recovery behavior, privacy controls, integrity checks, cloud safeguards, and
  transactional updates.

### Verification

- Backend: 1,740 tests passed and 1 skipped.
- Prototype package: 45 tests and 8 parameterized subtests passed.
- Frontend: ESLint, full JSX/checkJs type coverage, 201 tests, production build,
  and gzip bundle budgets passed.
- End to end: all 10 Playwright scenarios passed across desktop and mobile.
- Static and repository checks: Ruff, workflow parsing, repository contract
  validation, release/publication fault tests, and `git diff --check` passed.

## 2026.07.17.1

- Released the import-first Prep My Avatar fork with multi-reference dataset
  preparation, local and cloud training, checkpoint testing, and Studio flows.
