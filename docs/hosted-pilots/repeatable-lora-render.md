# Repeatable fal identity-LoRA render

`scripts/render_lora.py` prepares or resumes one private image render against
`fal-ai/flux-lora` or `fal-ai/flux-krea-lora`. Preparation validates the recipe
and local adapter checksum without making a network request. The `--execute`
flag is required to submit or poll a paid job.

Keep the recipe, run directory, and local adapter in ignored `data/` and
`output/` directories. The hosted adapter URL must point to the same weights as
the local `.safetensors` file. The script checks that file's SHA-256 before a
new submission; it does not upload the file. Rehost the same weights and update
the recipe if the URL expires. Never replace the adapter with different weights
under the same recipe.

Example recipe (`data/render-recipe.json`):

```json
{
  "endpoint": "fal-ai/flux-lora",
  "adapter": {
    "path": "fictional-avatar.safetensors",
    "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "url": "https://weights.example/fictional-avatar.safetensors"
  },
  "arguments": {
    "prompt": "A fictional person standing in a garden, natural light",
    "seed": 42,
    "image_size": "square_hd",
    "num_images": 1,
    "num_inference_steps": 28,
    "guidance_scale": 3.5,
    "output_format": "png",
    "lora_scale": 1.0
  }
}
```

Replace the example checksum with the SHA-256 of the local adapter. Prepare and
inspect the request locally:

```sh
python scripts/render_lora.py data/render-recipe.json --out output/render-01
```

Set `FAL_KEY` in the process environment, then explicitly submit or resume:

```sh
python scripts/render_lora.py data/render-recipe.json --out output/render-01 --execute
```

The run directory contains a private `run.json` record and, on verified
completion, `result.png`. `provider-error.json` holds provider error details
when available. Files are created with owner-only permissions where the
platform supports them. The credential is sent only to `queue.fal.run` and is
never written to the run record or printed.

If the wait window ends, the command reports `pending`; resume the same job
with the same recipe and output directory, or omit the recipe to use its saved
intent:

```sh
python scripts/render_lora.py --out output/render-01 --execute --wait-seconds 300
```

Temporary status, result, or image download failures keep the saved queue job
resumable. Retry with the same output directory; recovery continues from its
saved fal request and does not submit another job. A completed rerun verifies
the local image offline and does not require `FAL_KEY`.

An ambiguous submission timeout is recorded as `submission_unknown`. Inspect
the fal queue manually before taking any further action; the command will not
submit again from that record. Rejected and failed jobs also remain terminal.
A changed recipe conflicts with the saved run and requires a new output
directory. Invalid image bytes are preserved for inspection and are never
treated as a successful render. Run records include UTC creation and update
timestamps for later inspection.

A verified image means the provider returned the requested seed and a readable
PNG whose bytes are recorded by hash. It does not establish likeness or human
acceptance; assess those separately before using a render.
Hosted backend versions are not pinned by this command. Reusing inputs and a
seed does not guarantee identical pixels across requests.
