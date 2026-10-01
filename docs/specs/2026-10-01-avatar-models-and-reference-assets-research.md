# Avatar models and reusable reference assets

- **Status:** Offline export implemented and locally verified; still-image and silent-video pilots await execution inputs
- **Date / sources checked:** 2026-10-01
- **Scope:** Krea 2, Qwen Image 2.1, Fizgig and its training adapter, MiniMax H3 and RefMods, Ideogram 4.5
- **Verification:** Documentation reviewed; no models downloaded, training performed or generation quality independently measured

## Purpose

Prep My Avatar should prepare a consenting subject's identity for several useful
generation workflows: new photographs, edits to existing images, and consistent video.
The durable investment is the reviewed source corpus and its provenance. From
that corpus we should be able to create different model-specific assets as the
ecosystem changes.

This document collects the evidence and proposed product thinking in one place.
Recommendations below are our proposals, not claims that upstream tools already
integrate with this app. It complements the existing
[model/provider routing proposal](2026-08-28-model-provider-routing-design.md)
and [multi-reference corpus design](import-first-multi-reference-design.md).

For delivery boundaries, technical contracts and independent review, use the
[hosted export technical plan](2026-10-01-hosted-avatar-export-technical-plan.md).

## Initial use cases and priorities

The initial use cases are examples, not product defaults or eligibility
assumptions. Each user's subject, appearance, scenes, accounts, geography,
permissions and eligibility are data to capture and verify for that workflow.
The product must support another consenting subject without code changes.

- **Primary outcome:** a fresh photographic image bank of a consenting subject,
  including stage scenes, website/deck compositions and social quote images.
  Images should work with chosen backgrounds and leave useful space for text.
- **Next essential outcome:** silent B-roll using the same recognisable person.
  This is a crucial follow-on capability, not a distant optional experiment.
- **Deferred:** talking avatars, voice identity and lip synchronisation.
- **Delivery approach:** export first. Prepare reviewed datasets and reference
  packs for external tools before considering in-app creation or execution.
- **Execution:** preparation/review hardware, execution provider and asset store
  are user choices. The initial route proposes local preparation and managed hosted
  execution, with Hugging Face as a candidate store for compatible LoRAs.
- **Audience:** intended use and publication context must be recorded per run.
- **Source material:** historical photographs can inform framing and gestures,
  but fresh photographs should establish present-day appearance and fill any
  face, body or pose gaps.
- **Permissions and disclosure:** record the subject's consent, the user's
  applicable execution/publication permissions and disclosure preference per
  workflow. Do not infer them from this pilot or from account geography.

The desired result is a current likeness placed in useful scenes. Reconstructing
an old stage photo does not establish current appearance. Historical photos can
help describe framing and speaker gestures; fresh real photos should establish
the present-day identity. Keep capture dates and distinguish those roles.

These priorities replace the earlier unresolved choice between stills, silent
video and talking avatars. The working decisions below set the direction;
quality and compatibility claims still require experiments.

## Working decisions

These are pilot defaults, not assumptions about other users. The product should
select compatible recipes from maintained definitions and capture the chosen
settings and evidence. Users should not need to select model internals,
quantisation or node graphs unless a workflow requires it.

Keep the extension seams small: subject/corpus provenance, model and asset
compatibility, versioned recipes and formatters, provider lifecycle adapters, and
output import/evaluation. Pin changing endpoint capabilities, limits, prices and
offers with dated eligibility, quota and expiry evidence. The technical plan
requires a second recipe and fake second-service fixture to prove those seams;
fixtures do not establish hosted compatibility.

| Area | Decision | Reason |
| --- | --- | --- |
| First deliverable | Reviewed photo dataset, compact reference pack and creation manifest | Useful to external tools immediately; avoids coupling preparation to a trainer |
| Primary still adaptation | Krea 2 identity LoRA, Raw training and Turbo inference | Builds on the app's existing route and the model's documented use pattern |
| Still reference baseline | fal Nano Banana Pro edit with a reviewed identity subset, before paid adaptation | A named documented route establishes useful reference results without assuming existing app configuration |
| Next still candidate | Qwen Image 2.1 through Fizgig, initially an external comparison | Adds generation/editing research without replacing the existing workflow |
| First video route | Hosted H3 reference-to-video using images, initially on fal, subject to execution/output permissions | Matches the service-first preference without requiring custom RefMod nodes |
| Video scope | One person, short silent clips with simple actions and restrained camera movement | Matches the immediate need and makes identity failures easier to diagnose |
| Primary service | fal for hosted Krea training/generation and H3 reference video | Documented endpoints cover the two immediate goals |
| Secondary service | Replicate for verified model-specific alternatives, notably FLUX LoRAs | Explicit Hugging Face LoRA support exists for those endpoints; do not assume Krea parity |
| Asset store | Hugging Face for versioned personal LoRAs and creation metadata | Keeps the weights portable between compatible services |
| Hardware direction | Managed hosted execution; no local generation or training requirement | Use the user's chosen preparation/review workstation |
| Specialist fallback | RunPod-hosted Fizgig/ComfyUI only when a required asset is unsupported by managed APIs | Useful for RefMods, but not the normal workflow |
| Lower priority | Optimised RefMods, H3 LoRAs, LoKR, edit/slider adapters and multi-person scenes | Add them when a specific baseline failure or requested use justifies them |
| Deferred | Talking avatars, voice transfer and new Ideogram training support | Outside the immediate outcome; Ideogram 4.5 adaptation is not yet established here |

### Initial photo selection

Use a planning target of **40 accepted fresh photos: 32 creation inputs and eight
held-out evaluation photos**. This is a manageable initial experiment, not a
model requirement or a quota that makes poor photos acceptable. Select sixteen
references from the creation set; derive an eight-image compact subset where a
documented recipe or provider limit calls for it. Do not use the held-out images
as generation references during the comparison. Split original-photo families
before making derivatives; reject lineage overlap across held-out and creation
roles, and group near-duplicate burst shots. Prefer separately captured evaluation
views/outfits. Filenames or exact hashes alone cannot detect every related image.

Within the 32 inputs, aim for twelve face-focused views, twelve chest/waist-up
speaker poses and eight full-body views. Include both sides, natural expressions,
several outfits and more than one lighting/background situation. Preserve the
originals and reuse images across purpose-specific packs rather than requiring
separate photos for every target. Review the existing corpus first and request
new capture only for missing current views, with the subject's consent. An
optional T-pose is supplemental.

### Default experiment and escalation

For stills, use six representative scenarios: stage close-up, waist-up gesture,
full-body speaker, speaker beside a presentation screen, website hero with space
for copy, and social quote background. Try three fixed seeds per scenario per
compatible method. Use consistent scene briefs; adapt prompts to each model's
documented syntax rather than assuming identical prompts are fair.

An initial usable route must produce at least one publishable candidate in each
scenario without manual face replacement. Review at the intended display size
and inspect the face and hands closely. Track all attempts and corrections;
meeting that small pilot criterion does not prove general reliability.

Run the [fal Nano Banana Pro edit baseline](https://fal.ai/models/fal-ai/nano-banana-pro/edit/api)
first, with four reviewed identity views initially. Its documented image-list and
seed inputs establish an available interface, not tested likeness or account
readiness. Follow the technical plan's bounded comparison and terms checks, then
justify the Krea identity LoRA experiment from that evidence. Keep both
when each is useful. Prioritise the LoRA for repeated bank production if it gives
more reliable identity or materially less correction work. Do not train a new
adapter merely because reference generation exists, or dismiss adaptation based
on one successful reference image.

For video, begin with five-second silent clips: walking toward a
stage, turning toward the audience and gesturing beside a screen. Use two seeds
per action on the hosted reference endpoint. Require a usable clip for each
action with identity maintained throughout. Request no speech and deliver the
finished clip without an audio track, regardless of whether the service generates
audio. Compare a reviewed still animated through image-to-video when helpful.
Investigate plain/tuned RefMods only if native reference results are inadequate
and an external execution route supports the saved format. Do not assume a hosted
endpoint accepts them or that H3 Max accepts adapters made for another H3 build.

### Execution defaults

Managed services choose hardware and internal precision. Record the endpoint,
model/version when exposed, LoRA file revision, prompts, seed and generation
settings. Do not require GPU ownership or a local node editor.

The earlier 32 GB GPU / 64 GB RAM planning target now applies only to a specialist
external runtime if one becomes necessary. Fizgig and ComfyUI remain useful
research tools, not prerequisites for the normal image-bank workflow.

### Hosted service shortlist and asset flow

**First choice: fal.** The
[Krea 2 trainer](https://fal.ai/models/fal-ai/krea-2-trainer/api)
returns downloadable LoRA weights and configuration. The
[Krea 2 Turbo LoRA endpoint](https://fal.ai/models/fal-ai/krea-2/turbo/lora/api)
accepts custom LoRAs. The
[H3 Max reference endpoint](https://fal.ai/models/minimax/h3-max/reference-to-video/api)
accepts image/video/audio references; its reviewed input schema does not expose
RefMod-file or custom-LoRA input. Start with economical 768p five-second previews. The same endpoint offers 1080P latent refinement
from a native 768P source. Map identity/scene roles explicitly to numbered images,
and select within its twelve-file combined reference limit. Endpoint
availability is verified; likeness and interoperability are not yet tested.

**Second choice: Replicate.** Its
[LoRA guide](https://replicate.com/docs/guides/extend/working-with-loras/)
documents external weight loading, including Hugging Face, for specific models.
The [FLUX LoRA endpoint](https://replicate.com/black-forest-labs/flux-dev-lora)
provides a concrete still-image alternative. Its
[Krea 2 Large listing](https://replicate.com/krea/krea-2-large)
alone does not establish custom Krea 2 LoRA support. Keep Replicate as an
alternative when the selected endpoint explicitly accepts our model's adapter.
FLUX and Krea assets are separate; choosing another provider does not convert
one into the other.

Proposed flow (training is conditional on the reference baseline):

```text
Local workstation: curate photos and export
  → hosted still-reference baseline
  → assess whether adaptation adds useful repeatability or portability
  → if justified: managed training service
  → download weights/configuration and retain a backup
  → Hugging Face: version the personal LoRA
  → compatible fal/Replicate endpoint: generate using that LoRA
  → review and retain accepted images
  → hosted image/reference-to-video: create silent B-roll
```

If references already meet the use cases, retain that route and skip the training/
LoRA-storage branch unless a separate experiment is justified. Both branches lead
to a reviewed image bank and then the permission-checked silent B-roll pilot.

Hugging Face stores the asset; it does not automatically make every provider
support it. Pin the file revision, base family, trigger and preferred strength.
Prove a Hub-to-provider round trip with recorded asset hashes, nonzero strength
and recognisable identity; compare no-LoRA/LoRA controls where supported. Success
establishes that endpoint's compatibility, not universal portability. Keep returned images/clips in the private image bank rather than
depending on provider output links as permanent storage.

Use a **private Hugging Face repository initially**; hosting and public release
are separate choices. [Hugging Face visibility settings](https://huggingface.co/docs/hub/repositories-settings)
describe access controls. fal's file documentation expects fetchable URLs or
uploads, so a private Hub URL is not assumed to work directly. Where needed,
fetch privately and upload the selected weights to provider storage; assess that
storage's access/retention before execution. Do not place access tokens in asset
URLs or the public repository. A public LoRA remains an option if the user later
chooses easy anonymous access and reuse by others.

The service-first decision takes precedence over earlier trainer-specific
suggestions in this research. Export preparation should target the selected
hosted trainer's documented format; Raw/Turbo training details should be taken
from that recipe rather than imposed from the existing ai-toolkit config.

### Licence handling and personal data

Use Krea as the primary still route while Qwen remains a research/evaluation
candidate. The current
[Qwen licence](https://huggingface.co/Qwen/Qwen-Image-2.1/blob/main/LICENSE)
defines non-commercial use as research or evaluation only (section 1.i).
Accordingly, do not make it the default production image-bank route without
separate permission covering that use. This is a conservative project decision,
not a request for the user to interpret the licence without project guidance.

The technical plan's [execution and publication terms](2026-10-01-hosted-avatar-export-technical-plan.md#execution-and-publication-terms)
record Krea's revenue eligibility and derivative-distribution requirements and
H3's territorial/output restrictions. Execution geography does not alone settle
later worldwide publication. Confirm the actual hosted permissions and retain
the governing licence/version with user assets;
open-source application licensing does not grant rights to adapters or outputs.
Preserve required licence/notice material when sharing weights. Public generated
media disclosure remains part of the user's chosen publication workflow.

Keep source photos, reference packs and previews outside the public code
repository. Store personal LoRAs on Hugging Face under the visibility policy
above. Open-sourcing the tool does not require public release of identity assets.

## Source-photo plan for this use case

Proposed capture brief, to refine after reviewing the existing corpus:

| Group | Useful material | Purpose |
| --- | --- | --- |
| Current face | Sharp front, both three-quarter views and both profiles; neutral, smiling and expressive | Present-day likeness and changes of view |
| Speaker framing | Chest-up, waist-up and full-body; looking toward an audience, gesturing, holding a microphone or standing near a lectern | Actual image-bank scenarios |
| Whole person | Front, side and back views; natural standing posture, walking and seated views | Body proportions and wider compositions |
| Variation | Several outfits, backgrounds and lighting conditions | Evaluate whether identity survives changes instead of becoming tied to one outfit |
| Held-out evidence | A separate fresh set excluded from creation inputs | Judge whether the output resembles the person beyond the supplied examples |

A neutral arms-out/T-pose photo can be retained if useful for a specific pose or
whole-body reference experiment. It is not a prerequisite for a photographic
LoRA or RefMod, and should not dominate images intended to depict a speaker.
Ordinary natural gestures are more directly relevant to this image bank.

Preserve uncropped originals; derive face crops and wider reference packs
separately. The hosted Krea recipe square-crops inputs: preview and approve final
face/body framing, then review captions against the emitted derivative. Save
recipe-specific overrides without overwriting the master captions. A changed
crop invalidates that pair's prior caption approval. Review generated stage scenes for facial likeness, hands, microphone
geometry, body proportions, perspective and lighting against the background.
Evaluate intended website/deck crops and text placement, not only attractive
square portraits. Avoid treating generated stage scenes as records of an actual
event. Historical low-resolution photos need not become training inputs merely
because their setting is useful.

## What we already have

The app preserves originals, reviews quality and identity, maps coverage, selects
reference anchors, captions admitted training images, exports datasets and
records training snapshots. These capabilities remain useful across the new
targets.

The current [training-family list](../../backend/app/utils/training_families.py)
contains Z-Image, SDXL, Krea 2, FLUX.1 and FLUX.2 Klein. The
[Krea configuration builder](../../backend/app/services/lora_training_config_builder.py)
already distinguishes Raw training from an optional Turbo training route with
an assistant adapter. The [training setup guide](../guide/steps/06-training-tools.md)
currently centres on ai-toolkit. Qwen Image 2.1, H3, RefMods and Fizgig are
research candidates here, not verified app capabilities.

## The assets we should distinguish

| Asset | What changes or is stored | Why it matters for an avatar |
| --- | --- | --- |
| Character LoRA | Learned weight changes applied to a particular model | Reusable identity across prompted scenes |
| LoKR | Another parameter-efficient weight adaptation method | An alternative to compare when a trainer and inference loader support it |
| Plain RefMod | Encoded reference conditioning saved for reuse | A quick reference-based identity asset without a model-weight training run |
| Optimised RefMod | Reference latents tuned against a frozen model | A separate experimental route to improving reference behaviour |
| Training assistant adapter | A dependency active during a training recipe | Helps produce the personal asset; it is not itself that personal asset |
| Reference pack | Selected original/derived images and their roles | Portable inputs for native reference workflows and future asset creation |
| Edit dataset / edit LoRA | Before/after pairs and a learned transformation | A repeatable edit, which may be separate from learning identity |

A shared `.safetensors` extension does not establish interoperability. Nor does
using related encoders or VAEs establish that two models accept the same LoRA.
Each output needs a named model, creation method and tested use workflow.

## Krea 2: extend and validate the existing route

**Evidence.** Krea's [Raw model card](https://huggingface.co/krea/Krea-2-Raw)
positions Raw as a fine-tuning base, including LoRAs used on Turbo. Its
[Turbo model card](https://huggingface.co/krea/Krea-2-Turbo) is the corresponding
inference reference. Training instructions are available from
[Musubi Tuner](https://github.com/kohya-ss/musubi-tuner/blob/main/docs/krea2.md),
[SimpleTuner](https://github.com/bghira/SimpleTuner/blob/main/documentation/quickstart/KREA2.md)
and [Fizgig](https://github.com/shootthesound/Fizgig/blob/master/docs/KREA2.md).
SimpleTuner's hardware guidance varies substantially with resolution, precision
and offload; a minimum-VRAM claim is not a universal training requirement.

**Why add more support?** Krea gives us an existing still-image baseline against
which to judge the newer routes. Changing trainer should demonstrate a benefit
such as better likeness, easier evaluation or a workable hardware profile.

**Proposed fit.** Keep the corpus and captions reusable. Record the training
checkpoint separately from the inference checkpoint, and evaluate the output
on the intended Turbo workflow. Preserve the existing ai-toolkit route while
considering external trainer exports. Do not assume another trainer's defaults
match the current app recipe.

## Qwen Image 2.1: identity generation and image editing

**Evidence.** The [official model card](https://huggingface.co/Qwen/Qwen-Image-2.1)
describes a unified text-to-image and image-editing model, including transparent
RGBA output, with a 7B visual generation component. These are model capabilities;
they do not prove that a particular identity adapter works equally well in every
mode.

[Fizgig's Qwen guide](https://github.com/shootthesound/Fizgig/blob/master/docs/QWEN_IMAGE.md)
documents LoRA/LoKR training and paired-image edit LoRAs. Its training assistant
is frozen during training, disabled for previews and excluded from the saved
personal LoRA. The guide reports stability and sharpness improvements; those
are trainer-author findings requiring our own comparison. The
[adapter repository](https://huggingface.co/ShootTheSound/Fizgig-Qwen-Image-2.1-Training-Adapter)
exists but had no model card when checked, leaving its standalone documentation
and licensing details to resolve before adopting it.

**Why add it?** We could create new images of the person and investigate edits
that retain their identity. A separate edit adapter could encode a recurring
lighting or photographic treatment. Identity and treatment should remain
separate choices unless testing establishes a reason to combine them.

**Proposed fit.** Offer ordinary captioned identity datasets and, later, explicit
before/after edit pairs. Preserve pair correspondence and framing rather than
exporting edits as unrelated training images. Test identity in both generation
and editing, including whether an edit changes facial geometry or skin detail.
Keep assistant adapters and speed adapters separately identified in the recipe.

The [Qwen Research License](https://huggingface.co/Qwen/Qwen-Image-2.1/blob/main/LICENSE)
contains use and distribution conditions. Check the actual terms for the intended
use before distributing derivatives; open weights alone do not establish an
unrestricted distribution right. This document makes no legal determination.

## MiniMax H3: carry the identity into video

**Evidence.** The [official repository](https://github.com/MiniMax-AI/MiniMax-H3)
and [model release](https://huggingface.co/MiniMaxAI/MiniMax-H3) distinguish
first/last-frame generation (FL2VA) from reference-based generation (Ref2VA).
Ref2VA accepts image, video and audio references. The
[official reference prompt guide](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md)
explains how to assign reference roles in prompts.

[Fizgig's H3 training guide](https://github.com/shootthesound/Fizgig/blob/master/docs/MINIMAX_H3.md)
documents adaptation from photos, clips and sound/voice inputs, with clip previews.
It is evidence of a documented training route, not evidence that our photos will
produce a consistent face or voice on our hardware.

**Why add it?** The intended avatar could turn, speak, react and move through a
scene. This introduces temporal consistency as an acceptance criterion: a good
single frame cannot establish that a video maintains identity.

**Proposed fit.** Start with curated identity stills. Keep identity, movement,
style and audio references explicitly labelled by purpose. Later, consider clip
preparation only if it improves the intended output. Face crops alone may lose
body appearance and posture; retain wider originals and distinguish a face pack
from a whole-person pack. Voice identity is a separate capability to evaluate.

## H3 RefMods: creation guides and proposed workflow

### Documentation to start with

1. [Community creation and extraction guide](https://huggingface.co/datasets/malcolmrey/various/blob/main/h3-center/docs/MINIMAX_H3_REFMOD_CREATION_GUIDE.md): corpus selection, whole-folder extraction and direct extraction.
2. [Community installation and usage guide](https://huggingface.co/datasets/malcolmrey/various/blob/main/h3-center/docs/MINIMAX_H3_REFMODS_INSTALLATION_AND_USAGE_GUIDE.md): node installation, output folder and application workflow.
3. [Current RefMod node repository](https://github.com/Luisacaotica/ComfyUI-MiniMaxH3Mod): current controls, compatibility, reference mapping and known limitations.
4. [Fizgig RefMod creation and testing guide](https://github.com/shootthesound/Fizgig/blob/master/docs/REFMOD_HOWDOI.md): plain encodes, model-based optimisation and RefMod Studio.

The first two are community guides, not MiniMax's official model documentation.
They provide a useful starting point, but current node behaviour takes precedence
over older examples for a future experiment.

### What creation involves

The community creation guide proposes 8–20 clear images with varied views,
lighting and backgrounds. Its angle proportions are a starting recipe, not
established universal requirements. It describes encoding through the H3 video
VAE, saving conditioning and metadata in `.safetensors`, and using
`ComfyUI/models/refmods/`. It provides whole-folder and direct extractor methods.
Its 8,192-token example should not become an app-wide constant.

Fizgig documents a plain preset using eight photos at 1 MP and an optimised lite
preset using sixteen at 0.5 MP. Plain encoding needs no captions; optimisation
uses captions and a frozen H3 model. It distinguishes optimisation for Ref2VA
from FL2VA and records the target in metadata. These are alternative recipes to
compare, not a commitment to a particular count or size.

The node repository describes evolving controls and a default visual budget of
5,120 tokens. Compression or frame removal can damage motion timing. It also
documents experimental numbered-reference presentation, no automatic binding
of subject labels to loader slots, and unsuccessful speaker-identity transfer
in current tests. These limits qualify older community claims of automatic
multi-character mapping or instant identity guarantees.

### How this would fit Prep My Avatar

The following is a proposed product workflow, not an installation walkthrough:

1. **Choose the intended use:** still identity, moving whole-person identity,
   style reference or motion reference. Keep different people in separate assets.
2. **Build a reviewed reference pack:** choose real, clear images with useful
   variation; remove duplicates and identity ambiguity. Let the user inspect the
   selection and any crops. The entire training dataset need not become the pack.
3. **Export the pack and a creation record:** include image hashes, derivations,
   reference order and roles, chosen recipe, VAE and intended H3 checkpoint.
   Export is a useful first milestone even without running creation inside the app.
4. **Create externally:** establish a plain encoding baseline in ComfyUI or
   Fizgig. Compare optimisation separately so its benefit and cost remain visible.
5. **Inspect the resulting asset:** retain token count, creation settings, tool
   version and compatibility information alongside the source pack.
6. **Test in the intended generation workflow:** compare no-reference, native
   reference, plain RefMod and optimised RefMod routes using matched prompts and
   seeds where meaningful. Inspect the full clips against held-out real photos.
7. **Accept or revise:** keep the selected asset and its evidence linked. A newer
   recipe creates a new revision rather than replacing the reference originals.

**Why this is valuable.** Reference-pack curation is already close to the app's
strengths. A RefMod offers another reusable output and a relatively direct way
to investigate video identity before committing to weight training. It may reduce
repeated reference preparation, but small file size does not imply cheap H3
inference. More reference tokens can still increase generation cost.

**What needs caution in interpretation.** Reference conditioning can carry
clothing, backgrounds and photographic texture along with identity. Compression
can discard useful information. Optimisation can favour the examples it saw.
Attractive demonstrations justify an experiment, not a claim that the person
will survive every prompt. Hybrid LoRA/RefMod packaging remains a later topic;
first establish whether separate assets add measurable value together.

## Fizgig: a candidate companion, not a replacement decision

The [project overview](https://github.com/shootthesound/Fizgig) and
[CLI documentation](https://github.com/shootthesound/Fizgig/blob/master/docs/CLI.md)
cover Krea 2, Qwen Image 2.1, Klein and H3, along with asset inspection and
checkpoint comparison tools. The documented installation targets Windows/Linux
with supported GPU hardware; this does not establish native Mac suitability.

Our proposal is to investigate dataset/reference-pack export to Fizgig first.
Prep My Avatar would retain the master corpus, quality decisions and provenance;
Fizgig could create and inspect model-specific outputs. Decide on deeper
integration only after a manual workflow proves useful. Do not adopt automatic
recaptioning or image rejection as silent changes to the reviewed master corpus.

## Ideogram 4.5: generation/editing now, training unresolved

Runnable hosted documentation is available for
[text-to-image](https://fal.ai/models/ideogram/v4.5) and
[image editing](https://fal.ai/models/ideogram/v4.5/edit) on fal. That establishes
a provider route to investigate, not a personal LoRA training route.

The [launch discussion](https://www.reddit.com/r/StableDiffusion/comments/1wu98xe/new_model_ideogram_45_with_edit_open_source_soon/)
reports forthcoming weights and links an official announcement, but the linked
post could not be read during this research. The
[official news page](https://ideogram.ai/news/) did not supply a verifiable 4.5
open-weight release in the retrieved material. Treat weight availability,
licence and trainer support as unresolved; do not substitute Ideogram 4.0
documentation as proof of 4.5 compatibility.

**Proposed fit.** Consider it as a candidate for reviewed gap filling and edits
through the model/provider routing work. Add identity training to the discussion
only after an accessible checkpoint and documented trainer exist. Generated
images would retain provenance and pass the same admission review as other
synthetic candidates.

## Proposed evaluation and adoption order

| Research milestone | Question to resolve | Evidence needed before implementation |
| --- | --- | --- |
| Fresh-photo corpus and still reference baseline | Can reference inputs produce useful current stage images? | Reviewed current likeness; held-out comparisons; website/deck composition tests |
| Krea adaptation after reference baseline; Qwen research separately | Does a learned asset improve repeatability and flexibility? | Same source selection; controls showing adapter application; compatible outputs; identity, edit, cost and licence evidence |
| Hosted H3 reference video | Can the same corpus produce useful silent B-roll? | Execution/output permissions; inspected clips; comparison with animating an accepted still |
| Plain H3 RefMod, if needed | Does a reusable latent asset improve on managed references? | Verified external format support; comparison against native references |
| Optimised H3 RefMod | Does tuning improve unseen situations enough to justify its cost? | Matched plain/tuned comparison; correct H3 target; no unacceptable loss of flexibility |
| H3 LoRA and combined conditioning | Does learned identity add value beyond reference conditioning? | LoRA-only, RefMod-only and combined clip comparisons |
| Ideogram 4.5 adaptation | Are weights and a usable adaptation workflow available? | Verified release, terms, trainer and inference compatibility |

This order follows the confirmed priority: stills first, silent B-roll next.
Export preparation should preserve inputs for both from the outset. Initial
B-roll examples could include walking toward a stage, turning toward an audience
and gesturing beside a screen; audio and precise speech performance are outside
the initial acceptance criteria.

Use held-out real photographs as the identity reference. Exercise profile and
three-quarter views, expressions, wider framing, unfamiliar lighting, clothing
changes, occlusion and scenes beyond the source photos. For video, inspect turns,
movement, temporary loss of face visibility and reappearance throughout the clip.
Where multiple people matter, test separation and identity leakage explicitly.

Record likeness, prompt adherence, natural detail, clothing flexibility, temporal
stability, failures, wall time and resource cost. Automated face similarity can
help organise results; visual review remains necessary for body identity,
expression, artefacts and video continuity. Set acceptance thresholds after a
baseline experiment rather than inventing percentages from demonstrations.

## Understanding reference conditioning and deciding whether it is enough

Reference conditioning means giving a compatible generator photographs as part
of a request: use this person's appearance while making the requested scene.
A LoRA instead learns reusable model-weight changes from a dataset beforehand.
A plain RefMod packages reference information for reuse. An optimised RefMod
tunes that reference information against a model. The H3 mechanisms and the
plain/tuned distinction are documented in the guides above; still-image models
have their own reference interfaces and must be evaluated separately.

For this project, whether reference conditioning is enough is an experiment we
should help users interpret, not a technical preference they need to choose
in advance. Proposed decision rule:

1. Try a reviewed fresh reference pack across several representative stills:
   stage close-up, waist-up gesture, full-body speaker and quote background.
2. Check likeness across several outputs and unseen outfits, lighting and views.
   Log when a stronger reference also copies unwanted clothing or composition.
3. If it provides reliable usable images with acceptable effort, keep that route
   available. It remains useful even if a LoRA is later created.
4. If identity drifts or repeated manual correction becomes costly, compare a
   trained identity asset on the same scenarios. Judge the usable-output rate and
   total effort, not merely the best showcase from either method.
5. Repeat the native-reference/plain-RefMod comparison for silent H3 clips before
   deciding whether tuning or an H3 LoRA earns its additional work.

Reference inputs may be sufficient for occasional images; repeated image-bank
production may benefit from learned identity. That is a working hypothesis,
not a conclusion about this person's corpus. Fresh source photos make both
routes easier to assess without relying on repaired historical faces.

## Hardware, precision and inference workflow in plain language

**Hardware** is where creation and generation run. GPU memory (VRAM) is the
workspace available to the model; system RAM and disk also matter. Model size,
image resolution and video duration change the requirements. A tiny exported
RefMod still needs the H3 generator to produce a clip.

**Precision** describes how model numbers are stored and calculated. Labels such
as BF16, INT8, FP8 and 4-bit indicate different representations. Lower-bit model
storage can reduce memory use, but compatibility, speed and output differences
depend on the implementation. It is not the output image's resolution. Keep
original photographs at full quality regardless of execution precision.

**Inference workflow** means the steps used to generate the finished image or
clip: load the base model, provide prompts/references, apply any personal asset,
generate, decode and save. A hosted service may hide those steps; ComfyUI makes
many of them explicit. Training and inference are separate workloads.

[Fizgig's installation guide](https://github.com/shootthesound/Fizgig/blob/master/docs/INSTALL.md)
documents Windows/Linux GPU training and macOS preparation/captioning, plus
rented execution. It recommends 32 GB system RAM generally and more headroom for
H3 previews. Those are tool-specific starting points, not specifications for
hardware we have tested or a reason to buy a machine now.

**Chosen approach:** prepare and review locally, export, then use the external
managed services above. Hardware inventory is unnecessary for that normal path;
only a specialist fallback requires selecting a GPU runtime.
Hosted endpoints must explicitly support the required references or custom
assets; an image-generation API does not imply LoRA upload. No rental or upload
is authorised by this document.

Start from a documented hosted configuration, measure cost,
time and quality, then change one constraint at a time. There is no need for
users to select quantisation, GPU models or node graphs before we have
identified a useful output route. No hardware purchase is planned.

## Evidence to gather later, rather than decisions for the user

- Review current-photo coverage and produce a short missing-shot list.
- Pin compatible model/tool versions and verify the export formats they accept.
- Check publication terms separately from distribution of personal adapters.
- Verify Hugging Face-to-provider weight loading and selected endpoint costs.
- Perform the bounded comparisons above; retain complete results, not only winners.

At execution time, establish access to selected photos, the subject's consent,
an explicit spending ceiling before paid work, and the subject's likeness
approval on resulting candidates. Technical choices should be guided by
documented capabilities and evidence.

For preparation steps and private record templates, see the
[manual hosted-pilot kit](../hosted-pilots/README.md). It records no hosted
results. Before an experiment, recheck linked versions, complete the relevant
evidence checks and preserve a dated creation recipe.
