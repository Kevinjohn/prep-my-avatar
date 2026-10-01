# Manual still and silent-video pilots

Use this kit after creating a reviewed offline export. It supports [#51](https://github.com/Kevinjohn/prep-my-avatar/issues/51)
and [#52](https://github.com/Kevinjohn/prep-my-avatar/issues/52); it contains no
hosted results. Complete records privately, outside the application repository.
Do not commit photographs, identity weights, completed consent records or outputs.

## Prepare the private bank

Copy the templates into a private working directory. Keep the complete exported
revision unchanged, including its manifest and recipe, with a second private
backup. Record its SHA-256 in `readiness.json`. Keep originals returned by the
provider alongside accepted derivatives; temporary URLs are not an archive.

Suggested bank layout:

```text
bank/
  exports/avatar_export_<revision>/
  readiness.json
  briefs.json
  attempts/<attempt-id>/record.json
  attempts/<attempt-id>/originals/
  attempts/<attempt-id>/accepted/
  assets/<asset-sha256>/weights.safetensors
  assets/<asset-sha256>/configuration.json
  assets/<asset-sha256>/record.json
```

Use stable local relative paths and hashes in records. Never save credentials,
signed download URLs or tokens embedded in URLs. A provider request ID and private
repository/path/commit identify the remote evidence without retaining secrets.
For each `selected_uploads` or `references_in_order` entry, record the relative
path, SHA-256, role and order; the first frame has its own path/hash record. Each
`outputs` entry records a relative path, SHA-256, original/derivative relationship
and accepted status. Preserve failures using `request.error` even when there are
no outputs. Each timed observation records a clip timestamp and review note.

Hash each saved file with `shasum -a 256 <file>` (macOS/Linux) or
`Get-FileHash <file> -Algorithm SHA256` (PowerShell).

## Establish readiness before any upload

Complete every applicable field in `readiness.template.json`; null means unknown,
not approval. Identify the selected subject, consent evidence, exact selected
files and purposes, provider/storage route, retention/visibility, governing terms,
execution and later publication scope, and a combined currency-denominated spending
ceiling. Existing account credentials are not approval. Recheck prices and current
endpoint capabilities at execution. Estimates are not enforceable caps.

For free usage, record dated source evidence, eligibility, remaining quota and
expiry. Unknown or expired offers require a fresh route/cost decision; never
continue automatically as paid work or move photographs to another provider.

Keep held-out photos local for evaluation. Do not include them in training or
image-reference inputs. Resolve lineage/burst overlap before creating the pack.

## Run the still-reference baseline first

1. Edit the six scene briefs in `briefs.template.json` for the subject's actual
   use cases and choose three seeds per method. They are examples, not required
   appearance, geography or profession.
2. Check the current [reference endpoint contract](https://fal.ai/models/fal-ai/nano-banana-pro/edit/api).
   Initial candidate: four reviewed identity views explicitly described as the
   same person, scene references separately labelled, one PNG at 1K, explicit
   aspect ratio and web search disabled. Pin the complete recipe/settings with
   each attempt; a provider default is not a recorded parameter.
3. Use the service dashboard manually. Create an attempt record before submitting.
   Retain failed, rejected and unusable attempts as well as successes. An uncertain
   submission outcome is `unknown`, not permission to resubmit; check the dashboard
   and existing request ID first.
4. Download all results promptly and fill the attempt template. Review against
   held-out real photographs, including face, body, hands, copied surroundings,
   clothing flexibility and the final intended crop. Record correction effort and
   reported costs. The subject decides recognisable likeness.
5. Require at least one usable image per chosen scene. Save acceptance/rejection
   and reasons. Decide whether references solve the need before spending on
   adaptation. Identical seeds across different models do not imply equivalent
   compositions.

## Conditional learned-asset experiment

If the baseline shows a concrete expected benefit, record that decision and its
separate authorised budget. Check the current [Krea trainer contract](https://fal.ai/models/fal-ai/krea-2-trainer/api).
Use only the inner provider ZIP, never the entire private export package. Proposed
smoke/identity defaults are 100/1,000 steps at 1024 with reviewed captions and
`auto_captioning: "Off"`; these are unproven starting settings, not measured optima.

Save returned weights and configuration, hash both, and complete
`asset.template.json`. Verify the private storage commit and backup. Recheck the
exact base/checkpoint family and supported asset type; a `.safetensors` extension
does not demonstrate compatibility. Private Hub URLs are not assumed fetchable:
retrieve privately and use an explicitly authorised provider-storage route if
required, after checking visibility and retention.

Prove the exact stored asset on the chosen inference endpoint. Retain submitted
asset hash/locator, nonzero strength, actual settings and paired no-adapter/adapter
controls where supported. Repeat the scene comparison. A successful request or
weight download alone does not prove application or useful learned identity. If
training is skipped, record the reason and leave learned-asset support unproven.

## Silent B-roll

Use the same reviewed references and accepted first-frame candidates. Before using
[the initial video candidate](https://fal.ai/models/minimax/h3-max/reference-to-video/api),
establish the terms covering both hosted execution and intended later publication.
Keep unresolved rights as a blocker; a change of execution location is not evidence
of publication permission. A permitted replacement requires an explicit routing
choice and capability check.

Edit three simple actions and choose two seeds per action. Initial experimental
settings are five seconds, 768P, restrained camera movement and prompt expansion
disabled. Verify current input limits. Record numbered reference purposes/order
and the separate first-frame input; the master pack is not a request payload.
Inspect the whole clip, including turns, occlusion and reappearance. Record timed
observations and require at least one usable clip per action.

Keep the returned original privately. If it contains audio, create a separate
silent derivative using an installed FFmpeg:

```bash
ffmpeg -n -i original.mp4 -map 0:v:0 -c:v copy -an silent.mp4
ffprobe -v error -show_entries stream=index,codec_type,codec_name -of json silent.mp4
```

Confirm the probe reports video and **no audio stream**. Save the probe JSON,
command/tool version, original and derivative hashes with the attempt record.
Muting playback is not sufficient. No speech, voice cloning or lip sync is part of
this pilot. FFmpeg is needed only for this manual media step, not offline export.

## Report evidence

Separate local preparation, provider archive acceptance, exact asset loading,
subject-reviewed likeness and whole-clip identity. Keep #51/#52 open until their
real-media acceptance evidence exists. Report blockers with the precise missing
input and next action. Do not publish personal evidence without its own visibility
permission; public progress can identify counts and verification methods without
exposing identities or assets.
