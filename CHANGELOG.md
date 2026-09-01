# Changelog

All notable changes to Prep My Avatar are documented in this file.

The project uses calendar versions in the form `YYYY.MM.DD.N`. Changes remain
under **Unreleased** until a release is tagged.

## Unreleased

### Added

- Photo-variety analysis and captioning can now run through the configured
  local model, a connected ChatGPT subscription, the OpenAI API, or the Google
  Gemini API. Remote choices require an explicit per-action confirmation before
  dataset images leave the machine, preserve provider/model provenance, and do
  not pause ComfyUI while the remote provider works.
- Caption review now shows every kept photo beside its editable caption, and the
  face-similarity step shows the kept-photo grid with scored, non-scorable, and
  not-yet-analysed counts. Training preflight also identifies the exact photos
  with red or incomplete pixel QA, with full-size inspection and one-click
  rejection from the training set.
- Setup now includes a complete LoRA dependency map for Z-Image, SDXL, Krea 2,
  FLUX.1-dev, and FLUX.2 Klein, plus the hard gates checked for every launch.
  It links the exact gated Hugging Face repositories and provides a dedicated
  read-token field under the ai-toolkit setup step.
- Troubleshooting now records two dependencies exposed by the end-to-end run:
  a ChatGPT subscription does not fund OpenAI API usage, and access to a
  ComfyUI FLUX.2 Klein fp8 repository does not establish access to the separate
  4B or 9B training-base repository.
- Setup now leads into a separate **Start this session** check. Setup records
  whether each tool is configured; the session check reports whether local
  services are running now and links each stopped tool to exact startup steps.
- The ComfyUI setup page now presents two explicit installation routes:
  **Comfy Desktop** for an app-managed instance and **Git / code** for a
  user-managed clone and Python environment. Both routes include copyable,
  platform-appropriate setup and launch commands.
- Prep My Avatar now distinguishes a Comfy Desktop-managed folder from a
  Git/code installation. A configured folder containing
  `.comfy_environment` is treated as Desktop-managed; otherwise `main.py`
  identifies a Git/code clone. On macOS, the app also reads the installed
  Comfy application's `Info.plist` so it can use the real display name, bundle
  identifier and launch command instead of guessing an application name.
- ai-toolkit setup on macOS now offers a native Finder folder picker. The
  picker is restricted to local requests and the single supported ai-toolkit
  purpose; users on other platforms retain the text field.
- The first-run Markdown and HTML guides now include complete startup
  instructions for ComfyUI, LM Studio, Ollama, llama.cpp, quality helpers and
  ai-toolkit. The ComfyUI documentation records the Desktop-detection
  heuristic, why an installed Desktop app alone cannot identify a particular
  instance folder, and the limitation if a future Desktop release removes its
  marker file.

### Changed

- Remote identity generation now uses a compact five-image pack led by the
  primary portrait. Automatically selected references are ranked by measured
  face similarity and technical quality rather than framing diversity, and the
  prompt treats later photos as supporting evidence instead of averaging age,
  hair, facial hair, accessories, or body shape into a new person.
- Remote providers must pass a one-image identity canary before batch
  generation unlocks for that dataset and engine. The page shows the true
  one-image scope and cost, and only a result explicitly kept in Curation
  counts as likeness approval; rejected and pending outputs do not.
- The ai-toolkit setup step is now shown as partially ready when the core
  environment works but gated-model access is missing. It explains that any
  Hugging Face read token is valid—the token display name does not need to
  match the model, dataset, or trigger—and that repository access is verified
  separately when the model downloads.
- Training progress now advances only from optimizer updates that include a
  loss value. Model downloads, latent caching, and step-zero sample generation
  no longer masquerade as training steps; failed runs expose a substantially
  longer log tail so the webpage retains the actionable exception.
- OpenAI's explicit **Test** action now makes a small Responses API request and
  distinguishes missing API billing or quota from ChatGPT subscription access.
  External vision failures report credential, model-access, quota, rate-limit,
  provider, and malformed-response problems without logging keys or images.
- A zero-result photo-variety analysis or watermark scan is now reported as an
  incomplete check instead of a successful empty result. Training launch also
  retries transient checkpoint-list reads before deciding whether to resume or
  start over.
- Setup-owned Python and pip subprocesses no longer inherit interactive stdin,
  preventing a background install or environment check from waiting on an
  invisible prompt.
- The setup checklist now groups the five visible tools by what the workflow
  actually requires: at least one image-generation provider, local vision for
  automatic captioning and framing, and two genuinely optional enhancements.
  It no longer labels every setup step optional.
- Setup completion is independent of runtime state. A configured local tool
  remains **set up** while stopped; **running**, **ready**, and **not running**
  are reserved for the session check.
- Setup and session summaries now count the same five visible tool groups.
  Removed the unexplained ten-capability total, and replaced it with named
  requirement groups plus a five-tool session total.
- Session detail pages now preserve their origin when navigating back. Opening
  a tool from **Start this session** returns there instead of unexpectedly
  returning to the setup checklist.
- ComfyUI labels identify **ComfyUI Desktop** or **ComfyUI from Git / code**
  when the configured folder provides enough evidence. Desktop-managed
  instances are started through the Desktop dashboard; Git/code installs use
  their own verified virtual environment and `main.py` command.

- The four features that run a heavy ML model in its own interpreter — face
  similarity scoring, person masks, watermark inpainting and JoyCaption
  captioning — now share one description of how the app talks to those workers,
  instead of each restating the same stdin/stdout JSON protocol. The four copies
  had already drifted, and one of them reported a dead worker as a silent empty
  result rather than an error the user could see.
- A crashed ML worker now reports its own last error line — the message that
  actually names the problem — wherever it is reported at all, rather than in
  only some of the four features.
- Analysing an imported photo is faster: the exposure check reads the image
  histogram instead of walking every pixel in Python, and the two quality
  checks no longer make a full extra copy of the source image each. Scores are
  unchanged.
- The resolution tiers offered by the app now carry their display names
  alongside their sizes, so adding a tier can no longer produce a capabilities
  page that fails to load.

- The in-app updater now writes every one of its crash-critical files — the
  update journal, the restart receipt, the private recovery bootstrap and its
  manifest, and the restart request — through a single write-then-rename
  routine, instead of five hand-written copies of the same sequence. All five
  already agreed; keeping them in step by hand was the risk, in the one part of
  the app whose entire job is surviving an interruption.
- The updater decides "did this update change the Python dependencies?" and
  "did it change the front-end lockfile?" in one place each. The forward path
  used those answers to install, and the rollback path restated them in order to
  undo the install — so a change to one and not the other could have left the
  environment upgraded but never restored.
- After an update, the front-end is verified once: rebuilt from source when
  source changed, otherwise checked as a shipped bundle. Previously both
  conditions were computed, combined, and then re-tested inside the branch.
- Fixed a misleading trash-restore report: when rolling back a partly-completed
  operation, the items that were successfully put back are now the ones marked
  as rolled back. The four places that undo a batch of file moves now share one
  routine, and it reports which moves it actually reversed rather than assuming
  all of them succeeded.
- Trash entries that can no longer be restored are marked as such through one
  routine, so the two conditions that make an entry restorable are always stated
  together instead of one being set without the other.
- Directories holding deleted files are made owner-only through a single helper,
  so the permission fix cannot be applied in one place and forgotten in another.
- The integrity audit now reads each table once instead of re-querying several of
  them per check, and validates perceptual hashes with the same strictness as
  content hashes.
- Background job records now reject a wrong-shaped log or result column at the
  point they are decoded, rather than each reader repairing it separately — so a
  hand-edited or legacy row cannot become an error in one code path and be
  silently tolerated in another.
- Curation history resolves the dataset once per request and uses that answer
  everywhere, instead of re-deriving it from the caller's input at six separate
  points inside the same operation.
- Reddit and Sex.com now share one direct-media downloader instead of keeping
  byte-identical copies of it, along with the content-type tables that decide
  which formats are accepted and what extension a saved file gets. The three
  other scrapers that do the same job keep their own tables, because each
  deliberately accepts different formats — Civitai allows animation, the
  gallery-dl base allows video, and the concept import excludes GIFs.
- The gallery-dl scraper base now uses the shared atomic-write helper its
  siblings already used, rather than its own copy of the same
  write-to-temp-then-rename dance.
- The rule that recognises Bunkr's rotating domains — a check that guards what
  may be handed to an external downloader — is now written once instead of three
  times. The two allowlists that use it stay separate on purpose: they gate
  different tools with different exposure.
- Removed unreachable scraper code: a media-file validator and its magic-byte
  reader that nothing called, a serialiser on the URL validation result that
  nothing called, and an unused config import. This also leaves one copy of the
  image-signature table instead of two that had to be kept in step by hand.

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

### Removed

- Dead code in the analysis and ML-worker services: an error-detail helper that
  always returned nothing (while its documentation promised a field the app
  never sent), an unused interpreter lookup, an unreachable missing-file check,
  and a search-radius setting on the duplicate-image index that no caller has
  ever set and that could not have been widened without returning wrong answers.

### Fixed

- Replicate Nano Banana Pro requests now explicitly disable provider fallback,
  so an identity-critical request fails visibly instead of ever being eligible
  for silent model substitution.
- **Check photo variety** no longer reports completion merely because a plan was
  calculated. Unresolved framing or dimension targets keep the step in **Needs
  attention** until the photos cover them, the targets are changed, or the user
  explicitly accepts the current gaps. That acceptance is tied to the exact
  coverage snapshot and automatically expires after a photo or classification
  change.
- Gap recommendations now name each exact shot and represent every underfilled
  framing before suggesting additional shots from the largest deficit. Catalogue
  combinations that are not dataset requirements are labelled as optional
  variety opportunities instead of showing dozens of equivalent `missing`
  warnings.
- Local Klein generation now uploads staged references through ComfyUI's input
  API, so ComfyUI Desktop installations work even when their live input folder
  differs from the configured application folder. The legacy `beta57` workflow
  scheduler is also translated to current ComfyUI's supported `beta` scheduler.
  On Apple MPS, an fp8 checkpoint is cast through ComfyUI's default runtime
  dtype when memory permits; otherwise generation is blocked before fan-out
  with the live free-memory requirement instead of creating failed tiles.
- Failed local generation batches remain visible on the generation page with
  their recorded reason and a retry path; a batch can no longer fail and return
  to an apparently idle screen with no explanation.
- Remote engine cards now distinguish provider readiness from privacy approval.
  A connected ChatGPT plan remains visibly connected, and Nano Banana names its
  configured Google or Replicate route even while third-party transmission is
  disabled. Selecting a ready provider no longer requires hunting through
  Settings first: Generate presents a batch-specific confirmation naming the
  destination, reference-image count, prompt count, and estimated charge or
  plan-quota use before it records approval or transmits anything.

- Official Krea 2, FLUX.1-dev, and FLUX.2 Klein launches are blocked before
  export or process creation when no Hugging Face token is configured. The
  blocker names the exact selected repository, including the distinct Klein 4B
  and 9B training bases, rather than failing later with an empty `Bearer`
  header or an opaque HTTP 401.
- Training controls no longer become launchable while a collapsed preflight
  still contains a hard blocker; the first blocker remains visible without
  expanding the readiness panel.
- A reachable ComfyUI server no longer displays contradictory instructions to
  start ComfyUI. Its detail page now states that nothing needs to be started
  and shows the responding API URL; startup instructions appear only while the
  service is stopped.
- ComfyUI startup guidance no longer assumes that every installation has a
  repository-level `.venv`. Desktop-managed folders are directed to Comfy
  Desktop, Git/code folders without an environment receive the commands to
  create one, and unrecognised folders prompt the user to correct the path
  instead of showing a guessed command.
- The setup checklist no longer treats a correctly configured but currently
  stopped ComfyUI, LM Studio, or ai-toolkit installation as though setup had
  never been completed.

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
- The URL of a dataset image is now built in one place. Seventeen surfaces
  assembled the path by hand, which meant seventeen chances to forget the
  filename encoding — a photo with a space or a `#` in its name would simply not
  load, on whichever surface had missed it. The shared builder also decides the
  cache-busting rule once: a nonce only where an edit rewrites the file in place
  under the same name, so every other surface gets a cacheable URL.
- The framing vocabulary — face, bust, body, back — had five copies across the
  composition bar, the photo variety plan, the catalog and photo review, each
  with its own order, labels and colours that happened to agree. It is now one
  definition, so adding a fifth framing is one edit rather than a hunt. The
  body-fidelity training target stays where it is, because only one surface
  offers that choice.
- "Is this dataset ready to save?" is now one predicate shared by the create
  form and the settings modal, with tests. Both spelled the same three clauses
  out in a different order; a change to the server contract had two places to
  land and no way to notice it had only landed in one. Getting it wrong enables
  a button whose request the server rejects with a bare 400 and no explanation.
- The dataset grid no longer re-renders every tile when one checkbox is ticked.
  The tiles are memoised and the toggle handed to them is stable, which together
  take a selection change on a large dataset from ~6 ms to ~0.8 ms — memoisation
  alone bought nothing, because the changing handler defeated it. The derived
  pair sets the workspace hands its children are likewise derived once per image
  list, so their own memos start hitting.
- The training panel's status poll no longer re-renders the workspace every ten
  seconds to report that nothing changed, and the checkpoint browser no longer
  re-lists the checkpoint directory fifteen times a minute during a base
  conversion — both were reacting to a fresh object rather than to a changed
  value. Also removed dead navigation handling, moved four comment blocks back
  onto the code they describe, and renamed a flag that had stopped meaning what
  it said.

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
