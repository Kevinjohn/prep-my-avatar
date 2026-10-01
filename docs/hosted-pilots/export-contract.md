# Offline export extension contract

The hosted export reuses the existing dataset, kept-image admission and
`face_dataset_service.training_source_path` selection. It does not require an
installed trainer or provide remote execution. Completed packages are private
immutable revisions; their captured definitions are not looked up again when
reading them later.

- `hosted_export.list_sources` exposes corpus eligibility, lineage and role exclusions.
- `hosted_export.preview` materialises the exact role-specific image/caption pair. Approval binds source bytes, transform and both emitted hashes.
- `hosted_export.capture` checks selections, original/duplicate/burst lineage, approvals, source and database changes, and publishes a complete directory by rename.
- `hosted_export_recipes` validates maintained definitions and parameters, and selects a bounded archive formatter. Model identity, base family, asset kind and task are checked separately from the service identifier.
- Output import/evaluation remains the manual pilot kit. A future provider adapter owns its API protocol and lifecycle; corpus preparation must not gain provider-specific branches.

## Add a target

Create a versioned JSON definition under `backend/app/services/export_recipes/`
and register its `(id, version)` in `hosted_export_recipes.DEFINITIONS`. Include
model/base/asset/task compatibility, service capabilities, crop/caption policy,
archive name/formatter, input requirements, parameter schemas/defaults and dated
documentation/availability evidence. Validate defaults through `get_recipe`.
Definitions are maintained application data, not downloadable executable plugins.

If the archive layout needs code, add its small formatter in
`hosted_export_recipes.FORMATTERS`. Keep corpus and lineage selection unchanged.
A new process may need its own UI controls; it must preserve existing workflows.
Do not infer compatibility from a filename extension or rewrite a completed
export when updating defaults. The companion `recipe.json` records the full
selected definition and actual parameters.

`backend/tests/test_hosted_export.py` demonstrates a second fixture recipe with
preserved aspect ratio, nested pairs and a fake service, plus incompatibility and
historical-default checks. The fake service declares the offline preparation
protocol only. These tests do not establish a second provider's API lifecycle,
archive acceptance or hosted generation support. Expired/unknown offers are saved
as evidence and cannot cause execution because this boundary has no network or
submission operation.

## API and review records

The dataset's `/hosted-export` endpoint lists sources on GET and downloads the
completed outer ZIP on POST. `/hosted-export/preview` returns the exact PNG as a
data URL, emitted caption, image/caption hashes and pair hash. A selection carries
`image_id`, `role`, crop, optional caption override and the three approval hashes;
references also carry a purpose, with ordering determined by selection order.
Subject consent and source-rights basis are explicit request data. Held-out
selection cannot share original/duplicate/burst families with training/references.

Only the inner training ZIP contains trainer pairs. The outer package preserves
ordered reference/evaluation files, transforms, source lineage, selected and
excluded IDs, consent/rights declarations, definition/settings and file hashes.
Keep the outer package private and back it up before any manual provider use.

## Reference-only preparation

The maintained `reviewed-reference` v1 definition supports reference and evaluation roles, requires at least one reference and preserves framing. It emits the same private manifest/reference/evaluation contract without a training ZIP. It declares no model or provider compatibility. The Krea recipe retains its training minimum and trainer archive format.

Recipes declare supported roles and role-specific minima; legacy training definitions retain their training minimum. Changing recipes clears unsupported selections and approvals. Both recipes preserve held-out exclusion, source/caption hashes and immutable capture.

Completed revisions can be selected by the [private asset bank](bank-contract.md) for recorded manual attempts and returned output evaluation.
