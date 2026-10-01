# Hosted avatar exports: technical plan and review brief

- **Status:** Offline export implemented and locally verified; real hosted pilots remain untested and gated
- **Date:** 2026-10-01
- **Source baseline inspected:** `8a1a6f8120e3c9ecc901b5328bda1fc1ec96175e`
- **Evidence:** Focused source inspection and provider documentation; no hosted creation or generation tested

## Outcome and fixed direction

Prepare reusable assets for a consenting subject: photographic stills with
useful facial detail, whole-person coverage and composition, followed by short
silent B-roll that maintains identity through movement. Talking avatars and
voice work are deferred. Subject, appearance, scenes, accounts, geography,
permissions and eligibility are user data; the workflow must support another
consenting subject without code changes.

Deliver exports first. The current pilot evaluates fal, Hugging Face and
Replicate as candidate services and stores, not product-wide assumptions.
Preserve existing workflows and add small explicit boundaries for
corpus/provenance, model and asset compatibility, recipes and formatting,
provider execution, and output import/evaluation. Do not build a universal
plugin framework.

The [research and product direction](2026-10-01-avatar-models-and-reference-assets-research.md)
contains model rationale, source-photo guidance and reference/LoRA explanations.
This plan governs delivery boundaries and acceptance evidence. Where earlier
research suggests bespoke GPU execution, managed-service-first takes precedence.

## Current state: implemented versus prepared

| Area | Evidence and implication |
| --- | --- |
| Ordinary dataset export | [build_export_zip](../../backend/app/services/face_dataset_service.py) emits admitted `keep` rows as PNG/text pairs under `10_<trigger>/`, with provenance manifest version 2. Reuse the admission/caption/source rules; hosted archive compatibility is untested. |
| Export route | [dataset_export](../../backend/app/routes/datasets.py) streams a ZIP; backup is a separate route. Keep export and backup distinct. |
| Immutable training snapshots | [training_snapshot](../../backend/app/services/training_snapshot.py) records revision, configuration and content/caption hashes, checking for concurrent changes. Reuse where suitable; don't mutate existing snapshot formats casually. |
| Existing trainer materialisation | [lora_training_export](../../backend/app/services/lora_training_export.py) supports snapshot-based materialisation outside local ai-toolkit directories. It includes trainer-specific masks; those are not presumed useful to fal. |
| Settings and credentials | [config](../../backend/app/config.py) loads `.env` but does not include `FAL_KEY` in its Settings secret allowlist. A saved variable is not a completed integration. |
| Hosted account readiness | Account access, credentials, billing readiness and provider loading have not been verified. Do not infer them from local configuration or expose secret values in records. |
| Model families | [training_families](../../backend/app/utils/training_families.py) includes Krea 2. Qwen/H3/Fizgig/RefMods are not implemented training families in this app. |

## Delivered offline milestone

The [export contract](../hosted-pilots/export-contract.md) describes the implemented local API and archive. The export workspace now supports exact crop/caption approval, training/reference/held-out roles, lineage exclusion and immutable capture. Versioned definitions pin model capabilities and formatting; a second recipe and fake service are exercised only as local fixtures. Ordinary export and backup remain separate.

The [manual pilot kit](../hosted-pilots/README.md) supplies readiness, brief, attempt and asset records for the still-image baseline and silent B-roll. No hosted request, training, identity upload or generated person asset is demonstrated. Selected photos and consent, provider/storage access, execution/publication permissions and an explicit spending ceiling remain prerequisites.

## Initial delivery: an offline export package

Create one immutable export revision containing a provider upload archive and
private companion records. No API key or configured trainer is needed to export.
No network requests, paid jobs or automatic uploads occur at this milestone.

Proposed package:

```text
avatar_export_<revision>/
  krea_training.zip       # image/text pairs only; provider-specific layout
  references/             # ordered reviewed images for generation
  evaluation/             # held-out real images; not included in upload archive
  manifest.json           # private provenance, selection and file hashes
  recipe.json             # pinned recipe plus maintained definition references
  README.md               # manual training, asset storage and evaluation steps
```

These are proposed names/contracts, not existing files. Preserve ordinary export
behaviour and offer an explicit hosted target rather than silently replacing its
layout. The manifest is a companion document, not presumed trainer input.
Keep service/model IDs, capabilities, limits, defaults, availability, prices and
promotional offers in maintained definitions/settings. Pin definition and recipe
versions, evidence date and selected parameters into each export/run record so
later definition changes do not rewrite historical exports.

Use existing training admission rules plus a distinct held-out selection. A
reference may be chosen from the creation set without becoming an extra training
row. Held-out files must be excluded from both training and generation references
for the pilot. Keep filenames stable inside a revision, sanitised and free of
absolute host paths. Source originals remain in the master corpus; upload only
reviewed derivatives. Strip image metadata from upload derivatives and inspect
captions for incidental personal information.

The initial planning target is 32 accepted current creation photos and eight
held-out photos. Select sixteen references, then a smaller endpoint-compatible
subset for each use. Counts are guidance; actual limits belong to the endpoint
recipe. No automatic public publication of the photos or personal assets.

Assign creation/evaluation roles to original-photo families before deriving crops
or re-encodes. Reject shared source lineage across evaluation and training/reference
roles. Exact hashes alone do not detect sibling crops. Group near-duplicate burst
shots together; prefer a separate capture session or materially different poses
and outfits for evaluation. Record the grouping and any remaining similarity.

Capture every selected role, reference order, crop and caption override in one
revision. Detect concurrent changes to any of them; an interrupted or inconsistent
export must not appear complete. Build in a temporary location and publish the
completed revision atomically. Reuse existing snapshot guarantees where applicable,
extending their coverage to the additional selected records.

### Hosted Krea contract and crops

The [fal trainer](https://fal.ai/models/fal-ai/krea-2-trainer/api) documents an
image ZIP, same-stem `.txt` captions, trigger fallback and optional auto-captioning.
It returns weights/configuration and optionally its prepared dataset. Its current
resolution choices are 768 and 1024; preprocessing cover-resizes and centre-crops
to squares. Start with reviewed captions and auto-captioning off.

Require preview of the intended square training crop, with face/body clipping
warnings. Use a reviewed square derivative or exclude the image from this recipe
when cropping loses required subject content. Do not silently pad, stretch or
invent missing anatomy. Retain the wider original for references and other
trainers. Validate whether the trainer accepts archive subdirectories; default
the hosted adapter to root-level pairs, avoiding the existing repeat-prefix
convention. A later pilot must establish acceptance of the actual archive.

Review each caption against its final square derivative. Preserve the master
caption and record a target-specific override when removed content makes it
inaccurate. Hash the emitted derivative and emitted caption, and require renewed
caption approval after a crop change. A reviewed master caption does not by itself
approve a newly cropped training pair.

Do not hard-code the existing ai-toolkit Raw/Turbo settings into the hosted
recipe. Read the service's actual returned configuration. Proposed first identity
pilot: 1024 resolution for facial detail, 1,000 steps as a bounded starting recipe,
not a demonstrated optimum. After the reference baseline, run a 100-step archive/loading smoke test before
the 1,000-step identity experiment. The [listed trainer price](https://fal.ai/models/fal-ai/krea-2-trainer),
checked 2026-10-01, is $0.003/step with a 100-step minimum: approximately $0.30
and $3 respectively, excluding additional captioning, inference and storage costs.
The smoke test proves compatibility, not identity quality. Recheck pricing and
agree a combined pilot spending ceiling before submission.

## Records and small boundaries

Define versioned records at the boundary; begin with companion JSON rather than
requiring database changes for export-first:

| Record | Required information |
| --- | --- |
| Export revision | Format/schema version, dataset revision, selected roles, ordered references, relative filenames, content/caption hashes, crop transforms and source lineage |
| Subject/workflow authority | Subject reference, consent scope/status and date, intended use, execution geography, publication scope, disclosure preference and evidence reference; collect only what the user needs to establish the selected workflow |
| Creation recipe | Purpose, base family, provider/endpoint definition ID and version, explicit parameters, trigger, caption mode, source-document/check date; unknown fields remain unknown |
| Provider/model definition | Stable definition ID/version, declared capabilities and compatibility, accepted formats, parameter/file limits, defaults, availability, price basis and dated source/evidence |
| Promotional offer | Provider/offer ID, eligibility evidence, remaining quota and unit, expiry, dated terms evidence and whether the user selected it; never infer continuing eligibility or free usage |
| Personal asset | Kind (LoRA or future RefMod), SHA-256, base/checkpoint compatibility, creation revision, trigger/strength, Hub repository/path/commit, applicable licence/version and terms evidence when stored |
| Evaluation run | Scenario, method, asset hash, actual prompt/settings, reference order, seed, provider request identifier, saved outputs, review outcome and cost when reported |

Do not record tokens, signed URLs or credentials as provenance. Record provider
model versions only when exposed; seeds cannot promise exact reproducibility
across provider changes. Reject incompatible assets explicitly; a Krea LoRA is
not interchangeable with a FLUX LoRA, and a RefMod is not a LoRA merely because
both are safetensors files.

Keep five small boundaries explicit: subject/corpus selection owns admission,
lineage and provenance; model/asset definitions own declared capabilities and
compatibility; versioned recipes own process settings while exporters own target
format/crops/captions; provider adapters own request translation and lifecycle;
output import/evaluation owns downloaded outputs, evidence and review results.
Reuse existing seams after focused inspection; do not create a second corpus,
job queue or generic plugin system. Prove this extension boundary with a second
export recipe and a fake second-service fixture, including incompatibility and
error cases. Fixtures are local evidence only, not hosted service validation.

## Hugging Face and managed generation

Initially use private Hub storage with an asset card describing base family,
creation recipe, trigger and tested inference endpoint. Public release is a
separate visibility decision. Include applicable licence/notice files and any
required derivative naming when sharing or making an adapter available; retain
terms evidence even for private storage. Hosting and anonymous download choices
belong to the user.

The [Krea Turbo LoRA endpoint](https://fal.ai/models/fal-ai/krea-2/turbo/lora/api)
documents custom LoRAs and hosted file inputs/uploads. Private Hub retrieval and
end-to-end loading must be proven; an authenticated Hub URL is not presumed
fetchable by fal. If necessary, retrieve privately and upload the selected weights
to provider storage using its supported access controls. Never embed Hub tokens
in URLs or expose them to the frontend. Assess retention/visibility before use.

Keep a local/private backup of the weights and returned configuration. Download
generated output promptly, hash it and retain it in the private image bank;
temporary provider URLs are not the archive. Provider-native image generation
is the normal path. Replicate remains a verified-family alternative, not an
automatic failover: a second provider must not receive photos on failure without
the user's chosen routing policy.

## Reference baseline before adaptation

Use [fal Nano Banana Pro editing](https://fal.ai/models/fal-ai/nano-banana-pro/edit/api)
(`fal-ai/nano-banana-pro/edit`) as the named initial still-reference route. Its
schema accepts image lists and a seed. Documentation support is verified;
account readiness, identity quality and actual pack acceptance are not.
Use four reviewed identity views initially, explicitly described as one person;
keep scene references separate. Start at 1K, one PNG per request, web search off,
and explicit target aspect ratios. Check current file limits/terms before upload.
Use six scene briefs and three seeds, with held-out images used only for review.

Log likeness, anatomical detail, composition, unwanted copied clothing, usable
outputs, correction effort and cost. Compare methods using the same scene briefs,
not an assumption that the same seed produces equivalent scenes across models.
The baseline precedes LoRA expenditure; poor results do not automatically prove
that training will help. A Krea trial tests whether adaptation adds value.
If references already meet the use cases, retain them as a usable route and treat
any subsequent LoRA experiment as a separately justified portability/repeatability
test. No reference generator is presumed already configured in the app.

## Execution and publication terms

Before hosted execution, establish the selected subject's consent and the user's
applicable eligibility, execution geography, provider/storage access and intended
publication scope. Record evidence and check dates per workflow. Account location,
execution location, provider deployment and later output use/display are separate
facts; none is inferred from this pilot or treated as a product default.

The [H3 community licence](https://huggingface.co/MiniMaxAI/MiniMax-H3/raw/main/LICENSE)
sets territorial limits: section V.4 restricts outputs in certain territories
(UK/EU/US/Korea).
Therefore execution in an allowed territory does not establish rights for later
worldwide website, social or slide use. Confirm which fal-specific permissions
govern hosted H3 Max and the user's intended publication; use a permitted
alternative if unresolved. Retain the confirmation with run records. Do not
assume a rented runtime resolves this. The licence also requires prominent
disclosure for public generated content; record the user's disclosure preference
and meet applicable terms.

[Krea's v1 licence, dated 2026-06-22](https://cdn.jsdelivr.net/gh/krea-ai/krea-2@db3984fbc6e13b34c0064990fc2d95ac64d00058/assets/hf_samples/LICENSE.pdf)
permits community commercial use below $1m trailing annual revenue, including
affiliated entities; otherwise an enterprise licence is needed. Section 3 sets
derivative naming, licence/notice and modification requirements when distributing
models. Treat adapters conservatively as derivatives until applicability is
confirmed. Record the user's eligibility evidence and the terms governing hosted
outputs, downloaded weights and onward sharing separately. Preserve
provenance markings and provider safeguards; manually review outputs before use.

These checks do not block offline preparation. Before each relevant hosted pilot,
record the governing terms, check date, intended execution/publication scope and
whether evidence covers it. The document does not authorise paid work or public
asset release.

## Silent B-roll contract

Subject to the execution/publication terms above, start with fal's
[H3 Max reference-to-video endpoint](https://fal.ai/models/minimax/h3-max/reference-to-video/api):
five-second, 768p clips, explicit reference order, fixed seed and prompt expansion
disabled for controlled comparisons. Use images only initially. Its current input
schema supports a first frame plus reference images, but does not expose saved
RefMod/custom-LoRA input. Extra schema types do not prove an input is supported.

Choose at most twelve combined reference files under the current documented
limit; the sixteen-image master pack is not a request payload. Use a small image
subset initially. The prompt maps roles explicitly, for example: “Image 1 and
Image 2 show the same person from different views. Preserve that person's face
and proportions while they turn toward the audience. Image 3 supplies the stage
setting.” Record each submitted image's role and order; the first frame is a
separate field, not an assumed numbered identity view. The endpoint also offers
1080P refinement from native 768P; retain 768P as the economical pilot default.

Animate an accepted stage still as an alternative when it gives better identity
or composition. Deliver a file with no audio stream even if the provider produced
audio; keep any original output private for provenance. Use no voice cloning,
audio references or lip-sync acceptance criteria.

RefMods remain a valuable research option, with
[community creation](https://huggingface.co/datasets/malcolmrey/various/blob/main/h3-center/docs/MINIMAX_H3_REFMOD_CREATION_GUIDE.md)
and [Fizgig creation/testing](https://github.com/shootthesound/Fizgig/blob/master/docs/REFMOD_HOWDOI.md)
guides. Escalate to an external compatible runtime only if managed references fail
the actual use cases; it is not a prerequisite for shipping exports.

## Later API integration: minimum operational requirements

This is later scope, not part of the offline export milestone:

- Add `FAL_KEY` through the established backend secret-management path and expose
  presence only. Credential readiness, billing readiness and tested model support
  are distinct states. Saving a key must never run paid inference as a health check.
- Use asynchronous queue submission and status/result retrieval; no webhook or
  publicly exposed local callback is required. The [fal queue docs](https://fal.ai/docs/documentation/model-apis/inference/queue)
  support this lifecycle.
- Persist the remote request identifier before relying on process memory. After
  restart, reconcile existing jobs rather than submitting replacements.
- A timed-out submission has an unknown outcome. Do not automatically resubmit
  paid work unless idempotency or reconciliation proves duplication cannot occur.
- Model upload, submission, running, output retrieval and failure are separate
  states. Provider completion followed by a failed download is recoverable without
  retraining. Cancellation may not reverse charges already incurred.
- Require an explicit batch ceiling, estimate and selected upload pack before
  paid work. Reconcile actual charges when available; do not call estimates caps
  unless enforceable. Keep provider retries distinct from app resubmission.
- Validate endpoint-specific parameters and file limits. Download only approved
  provider/Hub resources with size/time limits; a custom weight URL is a server
  fetch boundary, not an unrestricted URL proxy.

Use fake responses for routine tests, including a fake second-service fixture
that exercises the provider boundary without changing corpus logic. Include a
second export recipe fixture to prove recipe/format additions preserve historical
exports. Record offer eligibility, quota, expiry and dated evidence; never assume
free usage continues or silently incur charges after expiry. Uploads to another
provider require the user's selected routing policy. Fixtures and mocks are local
evidence only. Live paid checks belong to an approved pilot, not normal CI. No new
JavaScript package manager, Docker support or production deployment is part of
this plan.

## Delivery sequence and acceptance evidence

| Milestone | Deliverable | Acceptance evidence |
| --- | --- | --- |
| 1: offline export | Explicit hosted ZIP, crop/caption review, reference/held-out packs and companion records | No API calls; source-lineage exclusion; emitted pair hashes; concurrent/interrupted changes cannot publish a completed package; unchanged ordinary export/backup; useful export with local trainers absent; second recipe fixture preserves prior export; fake second-service fixture exercises declared capabilities and failures |
| 2: reference baseline | Named reference endpoint, six scene briefs and three seeds | Subject consent, terms/upload scope and spending ceiling checked; all attempts/costs retained; user reviews likeness, composition and correction effort; results inform whether adaptation is useful |
| 3: manual adaptation and comparison | Krea smoke/identity training, saved asset, Hub-to-fal round trip and same six-scene comparison | Terms and total ceiling checked; archive accepted; saved weights/config hashes verified; asset locator/hash and nonzero strength logged; paired no-LoRA/LoRA control where supported; recognisable identity demonstrated; at least one usable image per scene without face replacement; inspect intended crops; actual costs retained |
| 4: silent B-roll pilot | Three simple actions, two seeds each | Hosted execution and intended output publication permissions established; at least one usable clip per action; identity stable through the full clip; final media contains no audio stream |
| 5: minimal integration | Settings, hosted job lifecycle and output import | Secret redaction, restart recovery, failed downloads and unknown submission outcomes tested without duplicate paid submissions |

Milestones 2–4 are experiments and can use service dashboards before integration.
A working Hub-to-fal round trip establishes compatibility for that exact asset
and endpoint, not automatic Replicate interoperability. Provider acceptance alone
is insufficient evidence of learned identity or actual application of weights.
An implementation reviewer checks the complete export-to-output chain once new code is
authorised. Unit/contract tests cover changed boundaries; browser verification
covers crop review and export UI. Re-run relevant checks after corrections, not
unchanged broad suites for reassurance. No schedule estimate is asserted before
review confirms the delivery boundary.

## Reviewer instructions

Review this plan read-only, together with the linked research and relevant source
above. Do not read `.env`, retrieve credentials, upload photos, create paid jobs,
change code, create issues or publish comments. The current task asks for a reviewable
document, not automatic execution by reviewers.

Assess:

1. Is milestone 1 the smallest complete useful outcome, and does it reuse the
   existing admission/export rules without losing provenance?
2. Are current facts distinguished from proposals and untested assumptions?
3. Will square crop preparation preserve the intended face and whole-body inputs?
4. Are held-out selection, reference ordering and asset compatibility sufficient
   to make the comparisons meaningful?
5. Is the private Hub-to-provider route realistic, and what remains to verify?
6. Does later job handling prevent duplicate paid submissions and recover output
   without repeating completed creation work?
7. Are licence/publication checks correctly separated from open-sourcing the app?
8. Are any abstractions, dependencies or milestones unnecessary for this internal
   tool? Suggest simplifications without silently dropping stills or B-roll.

Report all discovered concerns, including lower-priority observations, questions
and uncertainty. For each, cite the plan section/source location, explain impact,
and propose a concrete correction or evidence check. Use P0–P3 where applicable;
separate implementation blockers from experiment questions and optional changes.
State explicitly when no additional findings exist. Conclude with ready,
ready-with-corrections or not-ready for the offline export milestone, with reasons.

## Review corrections and remaining evidence

The ten review concerns are reflected in this revision:

| Concern | Disposition |
| --- | --- |
| H3 territory | User-specific execution context recorded; hosted/output permission remains an explicit pilot gate |
| Cropped-image captions | Final derivative review and target overrides required |
| Held-out leakage | Original lineage/burst grouping required before role assignment |
| Baseline sequencing | Named fal reference route precedes adaptation |
| Krea terms | Licence record, eligibility and distribution requirements documented |
| LoRA application | Nonzero-strength evidence, controls and likeness required |
| H3 reference roles | Prompt mapping and per-request subset recorded |
| H3 higher resolution | Existing 1080P refinement option acknowledged |
| Smoke pricing | Dated estimate and combined ceiling required |
| Package immutability | Whole-package concurrent-change and atomic completion checks required |

Corrections are documented, not implementation or a new independent review.
Offline export has a defined acceptance contract. Hosted pilots remain untested;
provider/storage compatibility, output quality and applicable rights need the
specified evidence before their execution or publication milestones.

No user decision is missing for document review. Access to selected photos,
subject consent, permission/access for chosen hosted stores, an explicit spending
ceiling before paid work and subjective likeness approval become relevant at
their respective execution milestones. Resolve technical uncertainty through
sources/evidence rather than asking users to choose model internals.

For private manual preparation and records, see the [hosted-pilot kit](../hosted-pilots/README.md), including the [readiness](../hosted-pilots/readiness.template.json), [briefs](../hosted-pilots/briefs.template.json), [attempt](../hosted-pilots/attempt.template.json) and [asset](../hosted-pilots/asset.template.json) templates. These provide preparation steps only; hosted results remain untested until recorded from an actual run.
