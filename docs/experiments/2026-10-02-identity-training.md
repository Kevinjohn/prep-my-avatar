# Identity adaptation experiments and next pilot

Recorded 2 October 2026. This is a sanitized operational record, not a publication
of the subject's photographs, identity weights, outputs or consent records.
Full private evidence stays outside version control. No new pilot has started.

## Outcome and scope

In this experiment, “LoRA” includes an identity adapter or a provider's equivalent
reference dataset. The current investigation concerns trainable image adapters.
Video is deferred; earlier subject feedback was favorable for Gemini Omni Flash
and MiniMax H3. Reference-only image systems are not the current investigation.

| Experiment | Subject assessment | Next use |
| --- | --- | --- |
| FLUX.1 dev, reviewed 30-image round | Good likeness; skin still looks synthetic | Accepted visual benchmark |
| Krea, 30-image round | Appears younger; regression | Retain evidence, not the preferred adapter |
| Full FLUX.2 dev through fal | Poor likeness | Rejected; retain recipe and outputs privately |
| Full FLUX.2 dev through Runpod | Poor and unusable | Rejected; checkpoints are diagnostic evidence only |

A technically successful training run does not establish useful likeness. The
previous provisional nomination of step 3500 is superseded by subject rejection.
No checkpoint from the Runpod round is accepted as a usable avatar.

## fal round

Trainer: `fal-ai/flux-2-trainer-v2`. Thirty reviewed photographs with caption
sidecars, 2000 steps, learning rate 0.00005, fallback caption identifying the
subject as a man, and `output_lora_format: fal`. Provider-reported execution was
approximately 55 minutes. The returned configuration does not expose rank,
alpha or timestep policy; do not infer the Runpod policy from this record.

Returned adapter and configuration were retained with hashes. Representative
frontal, three-quarter and full-body results were generated through
`fal-ai/flux-2/lora`, strength 1.0, seed 1042, 28 inference steps, guidance 2.5,
1024 square, prompt expansion disabled. Exact prompts and returned images are in
the private records. The subject rejected their likeness.

## Runpod round

Full FLUX.2 dev 32B, same 30-image/caption ZIP as the accepted FLUX.1 round,
five excluded holdouts, rank 16 / alpha 16, learning rate 0.00005, AdamW8bit,
batch 1, accumulation 1, 1024 native aspect buckets, frozen float8 base and text
encoder, and BF16 trainable compute. No simultaneous dataset or caption change.

The benchmark completed at step 250, then resumed with verified checkpoint
metadata and optimizer restoration. Checkpoints were saved every 250 steps
through 3500. Fourteen step saves, optimizer state, logs and 30 original samples
were retrieved and hash-verified. Every checkpoint has 320 finite F16 adapter
matrices spanning 160 modules, with consistent keys/shapes and changed weights
between successive saves. This demonstrates learning activity, not identity
acceptance or independent inference compatibility.

Training phases, including loading and validation: 5 hours 10 minutes.
Provisioning through recovery, verified collection and deletion: 5 hours
32 minutes. Measured steady training speed: about 4.9 seconds per step;
validation portrait generation: about 38 seconds. Reserved-rate estimate:
$12.19 at $2.20/hour, versus compute rate $2.09/hour plus storage. Billing snapshots
were still incomplete; $12.19 is not a final invoiced amount.

A long-lived SSH connection failed after training had completed successfully.
The controller stopped compute and preserved storage. Only that same pod was
restarted for collection, with no repeated training. Artifacts were verified
before deletion; independent provider inventory subsequently showed no pods.
The temporary monitor was paused. No automatic continuation remains active.

## Confirmed recipe mismatch, unproven cause

Both executed configs omit `train.timestep_type`. In the pinned trainer revision,
the config fallback is `sigmoid`, while selecting FLUX.2 in the UI sets `weighted`.

- `sigmoid` creates noise levels concentrated around the middle. The weighted
  policy's additional loss multiplier is absent.
- `weighted` creates a uniform 1000-to-1 schedule and applies the scheduler's
  predefined timestep-loss table. The table ranges approximately 0.445–1.523,
  with mean 1.0. It was originally derived using Flex.1-alpha; the UI default
  is not proof of an optimal human-identity recipe.

The mismatch affected the training noise distribution and loss contributions
throughout benchmark and resume. It did not change captions, preview prompts,
inference guidance, save format or checkpoint names. Correcting an inference
scheduler cannot retroactively change the trained weights. No traceback,
optimizer-restore failure or inactive-adapter evidence explains the result.
The mismatch is confirmed; its causal responsibility for likeness is not.

Pinned source evidence:

- [FLUX.2 UI default](https://github.com/ostris/ai-toolkit/blob/ecee894ed2b1f3716d9d7326693061ec1a3105bb/extensions_built_in/diffusion_models/ui.tsx#L851).
- [Config fallback](https://github.com/ostris/ai-toolkit/blob/ecee894ed2b1f3716d9d7326693061ec1a3105bb/toolkit/config_modules.py#L557).
- [Training timestep selection](https://github.com/ostris/ai-toolkit/blob/ecee894ed2b1f3716d9d7326693061ec1a3105bb/jobs/process/BaseSDTrainProcess.py#L1180).
- [Scheduler policy](https://github.com/ostris/ai-toolkit/blob/ecee894ed2b1f3716d9d7326693061ec1a3105bb/toolkit/samplers/custom_flowmatch_sampler.py#L115).
- [Loss weighting](https://github.com/ostris/ai-toolkit/blob/ecee894ed2b1f3716d9d7326693061ec1a3105bb/extensions_built_in/sd_trainer/SDTrainer.py#L967).

## Research implications

Supporting FLUX.2 training does not establish a reliable likeness recipe. Much
material labelled FLUX.2 concerns Klein, which differs from full dev; distinguish
those sources. The [Diffusers training guide](https://github.com/huggingface/diffusers/blob/main/examples/dreambooth/README_flux2.md)
documents the different families, quantized training and rank/alpha scaling, but
its example is not a validated real-person recipe.

A [firsthand full-dev report](https://www.reddit.com/r/StableDiffusion/comments/1rcu82s/training_characterface_loras_on_flux2dev_with/)
describes successful fictional-character training with ranks 32/64 and learning
rate 0.00005. Outputs were withheld, and replies disagree on settings. This is
an experimental lead, not independent proof of a universal recipe.

All actual captions describe pose, clothing and setting without explicitly
captioning permanent face geometry, age or beard color. The earlier suspicion
that captions assigned those features away from the trigger has no direct
support. Some images have small faces, occlusion or difficult lighting; that
warrants a later controlled selection test, not declaring the bank defective.

The existing images were already poor in resident trainer previews. An exported
adapter loading test is needed for reproducibility but cannot alone explain those
poor previews. The [matching inference implementation](https://ai-toolkit-docs.runcomfy.com/models/flux2/)
helps establish appropriate loading, scheduler and scale behavior. The known
[single-control edit bug](https://github.com/ostris/ai-toolkit/pull/629) does not
apply to this run, which supplied no control images.

## Saved tests and remaining gaps

Reuse the 30 stored Runpod previews: frontal seed 314159 and three-quarter seed
271828, at step 0 and all 14 checkpoints, 25 inference steps, guidance 4, 1024
square. They came from resident adapter state; no per-checkpoint reload was
performed. Do not repeat them merely to reproduce a comparison sheet.

No Runpod full-body output was saved. Accepted FLUX.1 frontal/three-quarter images
use different prompts/seeds and are visual benchmarks, not matched controls.
A matched three-view comparison therefore needs only the missing tests. Reuse
the saved FLUX.1 full-body image and its prompt/seed. Human likeness judgement
against real holdouts remains the acceptance criterion.

## Agreed next pilot

1. Review saved evidence before spending; that review is complete.
2. Fill missing existing-checkpoint tests with three simple views and fixed seeds,
   reusing saved tests and the accepted FLUX.1 benchmark.
3. Make one training correction: explicit `train.timestep_type: weighted`.
   Keep the dataset, captions, rank/alpha, LR and other settings unchanged.
4. Start a fresh job, not a resume of the old sigmoid-trained weights. Save every
   250 steps. Set a hard 60-minute maximum GPU runtime, including setup, sampling
   and existing-checkpoint testing. Reserve collection/stop time before expiry.
5. Measure actual speed early. At the previous rate, 250 training steps take
   about 20 minutes and 500 about 41 minutes, excluding setup. Start conservatively
   at 250; never assume 500 will fit. The previous multi-hour guard is unsuitable.
6. Show early comparisons and stop. Continuation requires the human subject's
   judgement of meaningful movement toward likeness, not attractive images.
7. If progress is absent, investigate data or training method instead of extending
   automatically. Weak likeness at 250 is inconclusive about eventual learning:
   the original run only began appreciable movement around 500–750. Respect the
   runtime ceiling regardless.

## Private retention

The ignored private experiment directories contain the executed recipes, provider
responses, exact prompts, numerical review, controller/recovery scripts, weight
files and images. Stable backups include all 14 checkpoints and a verified bank
archive. The app bank retains all 30 Runpod samples and one diagnostic checkpoint;
independent consumer loading and likeness acceptance remain unverified/rejected,
respectively.

Private backup locations and evidence filenames are indexed in
[the retention record](2026-10-02-retention.json). This commit does not move private
media or credentials into Git and does not start a new experiment.
