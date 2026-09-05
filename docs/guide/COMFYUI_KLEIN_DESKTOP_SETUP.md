# ComfyUI Desktop: FLUX.2 Klein setup

This records the working ComfyUI Desktop setup completed on 2026-08-31 for
Prep My Avatar. It also provides repeatable recovery steps if the models need to
be installed again.

## Installed configuration

- ComfyUI Desktop instance: `ComfyUI-desktop`
- ComfyUI API: `http://127.0.0.1:8188`
- ComfyUI application directory:
  `/Users/kevinjohngallagher/ComfyUI-Installs/ComfyUI-desktop/ComfyUI`
- Shared model directory visible to the instance:
  `/Users/kevinjohngallagher/ComfyUI-Shared/models`
- Download destination selected by ComfyUI Desktop:
  `/Users/kevinjohngallagher/ComfyUI-Installs/ComfyUI-desktop/ComfyUI/models`

Prep My Avatar is configured with the **application directory**, not the shared
models directory. Its installer derives the correct `models` subdirectories
from that location.

## How Desktop ownership is detected

Prep My Avatar resolves the configured application directory and inspects it
locally. A `.comfy_environment` file identifies a ComfyUI Desktop-managed
instance. Without that marker, a directory containing `main.py` is classified
as a Git/code installation; without either marker, the installation type is
unknown.

On macOS, Prep My Avatar separately scans `/Applications` and
`~/Applications`, then reads a matching app's `Info.plist` to obtain its real
name, bundle identifier, and launch command. Finding the application is not
proof that a particular folder belongs to it because Desktop and a standalone
Git clone can coexist. The `.comfy_environment` file is the folder-specific
evidence.

This detection is a filesystem heuristic rather than a permanent ComfyUI API
contract. If a future Desktop release removes the marker, an instance that
still contains `main.py` may be labelled as Git/code until the detection is
updated. No paths, usernames, or installation types are hardcoded for this
machine; every configured directory is inspected using the same rules.

## Files and destinations

The current Prep My Avatar workflow is the FLUX.2 Klein **9B fp8** workflow. The
4B model files shown in some ComfyUI tutorials are not substitutes for this
workflow's 9B model and 8B text encoder.

| Asset | Hugging Face repository | Destination relative to the ComfyUI application directory |
| --- | --- | --- |
| `flux-2-klein-9b-fp8.safetensors` | `black-forest-labs/FLUX.2-klein-9b-fp8` | `models/unet/klein/` |
| `qwen_3_8b_fp8mixed.safetensors` | `Comfy-Org/vae-text-encorder-for-flux-klein-9b` | `models/text_encoders/` |
| `flux2-vae.safetensors` | `Comfy-Org/vae-text-encorder-for-flux-klein-9b` | `models/vae/` |
| `Flux2-Klein-9B-consistency-V2.safetensors` | `dx8152/Flux2-Klein-9B-Consistency` | `models/loras/klein/` |

The diffusion model, text encoder, and VAE are required. The consistency LoRA
is optional but recommended by Prep My Avatar because it helps preserve
composition between edits.

## What was done

1. Opened ComfyUI Desktop and selected **Standalone ComfyUI-desktop → Storage**.
2. Confirmed that the instance reads shared models and that newly downloaded
   models belong under the instance's `ComfyUI/models` directory.
3. Entered the ComfyUI application directory above on Prep My Avatar's
   **Setup → Local image provider — ComfyUI** step and selected
   **Save & re-check**.
4. Confirmed that Prep My Avatar found the installation and that ComfyUI was
   running at port 8188.
5. Used Prep My Avatar's one-click installers for the public text encoder, VAE,
   and consistency LoRA. These installers create the destination directories and
   stream each file directly into place.
6. Confirmed that the Hugging Face account already had access to the gated
   `black-forest-labs/FLUX.2-klein-9b-fp8` repository.
7. Downloaded the gated 9B fp8 model through the authenticated Hugging Face
   browser session, then moved it from Downloads to `models/unet/klein/`.
8. Selected **Load All Folders** in ComfyUI's Model Library to rescan without
   discarding the open unsaved workflow.
9. Re-ran **Save & re-check** in Prep My Avatar and verified the Klein capability.

No Hugging Face access token was created or copied into Prep My Avatar. The
gated model download used the existing authenticated browser session. For a
future unattended reinstall, create a read-only token at Hugging Face only after
accepting the model licence, then save it as **Hugging Face token** under
**Settings → Local tools**; the one-click Klein model installer can then use it.

## Verification

After the downloads finish:

1. Check that all four files exist at the destinations in the table and have
   multi-megabyte or multi-gigabyte sizes. A tiny HTML or text file means an
   authenticated download failed and must not be renamed as a model.
2. In ComfyUI, open **Models** and select **Load All Folders**. A full instance
   restart also works, but save the open workflow first: ComfyUI Desktop warns
   that restarting discards unsaved workflow changes.
3. Confirm that the Model Library shows one entry in each of `diffusion_models`,
   `loras`, `vae`, and `text_encoders` for a clean installation of this stack.
4. In Prep My Avatar, return to the ComfyUI setup step and select
   **Save & re-check**. The page should report that ComfyUI is found and Klein is
   available.

The installed files were verified with these SHA-256 hashes:

| File | SHA-256 |
| --- | --- |
| `flux-2-klein-9b-fp8.safetensors` | `865ba09f5b4c3cbd3468a4bd3acb9fcb2f8740c54317482f0bcd4ed1d3655cee` |
| `qwen_3_8b_fp8mixed.safetensors` | `abad16806e0cbabc54e0325d6565847443fe396d5f0be38bb3cd3fe75a1201d6` |
| `flux2-vae.safetensors` | `868fe7b343cc8f3a19dbcfcafbc3d5f888802be3f89bd81b65b3621a066ce8f3` |
| `Flux2-Klein-9B-consistency-V2.safetensors` | `61db2017ce420b97bd5ef11984e5a894c90003a6bbf0dc9473f8d7b9ebb3ff93` |

If a file is missing, repeat only that asset's download. Do not download a 4B
model or a generic Qwen encoder to fill a 9B filename: incompatible encoders can
load but fail later with matrix-shape errors.

## Storage and hardware notes

Allow roughly 19 GB for these four downloads. Model file size is not the same as
runtime memory use; check the hardware guidance shown by Prep My Avatar and the
official model card before attempting a generation. The files can be kept in a
shared model directory instead, but then ComfyUI Desktop and Prep My Avatar must
both be configured to resolve that directory consistently.
