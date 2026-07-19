# Changelog

All notable changes to Prep My Avatar are documented in this file.

The project uses calendar versions in the form `YYYY.MM.DD.N`. Changes remain
under **Unreleased** until a release is tagged.

## Unreleased

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

- Backend: 1,353 tests passed and 1 skipped in the complete suite; the final
  dataset-service regression suite passed 78 tests and the training-service
  suite passed 42 tests.
- Frontend: ESLint, typecheck, 78 contract tests, and production build passed.
- End to end: all 4 Playwright scenarios passed across desktop and mobile.
- Static checks: Ruff and `git diff --check` passed.

## 2026.07.17.1

- Released the import-first Prep My Avatar fork with multi-reference dataset
  preparation, local and cloud training, checkpoint testing, and Studio flows.
