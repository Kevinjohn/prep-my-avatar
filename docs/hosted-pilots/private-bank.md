# Private asset bank

The private asset bank keeps the local evidence for manual still-image, adaptation
and silent-video attempts. Open it from the dataset's **Export dataset** step.
It does not submit requests, upload photographs or fetch provider URLs.

## Prepare and record an attempt

Create a reviewed export first. Choose the reference-only recipe for the initial
still-reference baseline; use the Krea training recipe only when training material
is needed. Keep evaluation photographs separate from all generation inputs.

In **Private asset bank**, select the completed export and a process recipe. Review
the model, provider, endpoint and actual settings. Select reference images in their
submitted order and record their purposes. Video can reuse an accepted imported
still as its separate first frame. Model-specific weights require matching declared
compatibility; a matching declaration does not prove that a provider loaded them.

Save the prompt, seed and scene/action notes before the manual request. Follow the
[readiness and spending checks](README.md#establish-readiness-before-any-upload)
outside the application before using a provider. The bank is a record of work, not
an upload or spending authorisation.

After a request, update its status, request identifier, costs and any error. Keep
failed attempts even when they have no files. If submission has an uncertain
outcome, record **unknown** and reconcile the existing request in the provider's
dashboard before trying again. The application never retries a hosted request.

## Retain files and evaluate each result

Download returned files from the chosen provider yourself, then import them into
the matching attempt. Images, video, model weights and configuration are retained
locally with their exact file hashes. Imported originals are not overwritten by
reviews or silent derivatives. Do not enter credentials, access tokens or signed
URLs into records or configuration files.

Open the attempt’s held-out photo comparison to inspect the saved evaluation views. These remain review-only files and cannot be selected as generation inputs.

Review each image or clip separately; one accepted output does not accept every
file in an attempt. Record likeness, face and body/hands detail, composition and
final crop, correction effort and the acceptance reason. For video, watch the
entire clip and record timed observations through turns, occlusion and reappearance.
The subject's likeness assessment remains a human judgement.

Weights and configuration are reusable records, not proof of a working adapter.
Retain their model/base/checkpoint and rights evidence. Record exact loading and
paired-control evidence from real execution before claiming useful application.
The presence of a file or successful request alone does not establish that claim.
Use **Update asset compatibility and evidence** to add declarations and rights,
storage or backup evidence without importing the file again. Previously recorded
attempts retain the compatibility evidence they selected.

## Silent video

When FFprobe is installed, the bank inspects the stored clip and records stream
evidence against its exact hash. A silent result must contain a video stream and
no audio stream. Missing tools or failed inspection leave the result unverified.
A review checkbox cannot establish silence.

When FFmpeg is available, create a silent derivative from the imported original.
The original stays intact; the derivative records its parent hash and receives
its own stream check and review. Removing audio does not establish stable identity
or automatically accept the derivative. FFmpeg and FFprobe are optional for other
bank functions and are not installed automatically.

## Keep a private archive

Download the dedicated bank archive after meaningful work. It contains the bank
records, retained files and linked export evidence so temporary service URLs are
not the only copy. Store a second private copy and verify its contents and hashes.

**Ordinary dataset Backup does not include the private asset bank.** Keep both
archives when backing up the corpus and its creation results. The bank archive is
portable evidence and media retention; it is not an ordinary dataset-import ZIP.
Deleting a dataset follows the application's existing dataset/Trash lifecycle.
Do not publish the bank archive with the software repository.

## What local verification establishes

Synthetic images, clips and model-file fixtures can establish retention, hashing,
role isolation, compatibility rejection, review persistence and silent-media
handling. They cannot establish provider acceptance, exact learned-asset
application, real likeness, model/output rights or useful motion. Those remain
separate acceptance evidence for the real still and video pilots.
