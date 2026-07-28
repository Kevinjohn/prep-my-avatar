# ComfyUI input-schema fixtures

`object_info-core-v1.json` is the versioned reduced `/object_info` projection
for the real ComfyUI node classes used by the checked-in API workflows.
`object_info-custom-fake-v1.json` supplies deterministic fake schemas for the
optional/custom node classes those workflows require. The projection retains
only node names and accepted input names; model lists and machine-specific
values are deliberately omitted.

When a workflow begins using another node or input, update the applicable
fixture in the same change. Protocol tests merge both documents and validate
every active workflow on all backend CI platforms.
