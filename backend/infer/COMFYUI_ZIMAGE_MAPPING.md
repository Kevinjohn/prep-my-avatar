# ComfyUI Z-Image mapping provenance

`z_image_to_diffusers` in `convert_comfy_zimage_to_diffusers.py` is vendored
verbatim from:

- project: ComfyUI (`Comfy-Org/ComfyUI`)
- revision: `5151cff293607c2191981fd16c62c1b1a6939695`
- source: `comfy/utils.py`, lines 678–742
- upstream change: “Add some missing z image lora layers” (#10980), committed
  2025-11-29
- source URL:
  <https://github.com/Comfy-Org/ComfyUI/blob/5151cff293607c2191981fd16c62c1b1a6939695/comfy/utils.py#L678-L742>

The vendored function is Copyright (C) Comfy contributors and is licensed under
GNU GPL version 3 or (at your option) any later version. The upstream license is
available at:
<https://github.com/Comfy-Org/ComfyUI/blob/5151cff293607c2191981fd16c62c1b1a6939695/LICENSE>.

Only the identified function is copied. Local checkpoint inspection, conversion,
validation, CLI handling, and persistence code surrounding it are not represented
as upstream ComfyUI code. The pinned compatibility fixture in
`backend/tests/fixtures/zimage_mapping_comfyui_5151cff.json` records representative
QKV slices, transformer/refiner keys, and basic key renames independently of model
downloads.
