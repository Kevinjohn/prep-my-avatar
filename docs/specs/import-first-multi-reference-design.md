# Import-first, multi-reference dataset flow

## Goal

Extend the upstream guided workspace so a user can start with a large folder
of real photographs, understand what the corpus already covers, and use image
generation only to fill deliberate gaps.

The existing upstream character flow starts from one primary reference and
fans out a catalogue of generated shots. This fork keeps that flow available,
but adds an import-first path alongside it.

## Concepts

### Reference pool

All user-supplied images that may help establish identity or coverage. The pool
can be large and is never sent wholesale to a provider by default.

### Anchor set

A selected, diverse subset of the reference pool used for one generation
request. Selection should prefer sharp, identity-clear, non-duplicate images
with complementary views and framings. The chosen filenames, imported row ids,
and selection reason must be stored with the generated candidate. The current
API default selects up to 14 anchors; the pool itself is not capped by that
request limit.

### Coverage plan

The current corpus analysed by view, framing, expression, lighting, and other
available annotations. Each dimension distinguishes `covered`, `weak`,
`missing`, and `unknown` rather than treating unavailable analysis as absence.

### Generated candidate

An image produced by Nano Banana or another engine to address one or more
coverage deficits. Generated candidates must retain their engine, prompt,
anchor set, request status, failure reason, and source relationship.

### Training set

Only images explicitly accepted after review. Imported and generated images may
both enter it, but provenance remains visible and export preflight must be able
to report the mix.

## Target flow

1. Import a folder or add individual photographs.
2. Preserve originals and analyse technical quality, duplicates, and coverage.
3. Review the corpus and select identity anchors.
4. Show a live coverage plan with actionable deficits.
5. Offer generation presets that target missing combinations only.
6. Generate candidates using a bounded, diverse anchor set.
7. Review imported and generated images in one curation surface.
8. Caption, run preflight, and export or train.

## Migration map

| Prototype capability | Fork destination |
|---|---|
| `analyse_image` | Dataset import/analysis service and per-image metadata |
| `mark_duplicates` | Import deduplication and curation warnings |
| `coverage_lines` | Live composition/coverage panel and downloadable report |
| Original preservation | Per-dataset `originals/` storage plus provenance fields |
| Local HTML decisions | Upstream dataset review state and guided workspace |
| Captioned exports | Upstream training ZIP plus model-neutral export extensions |

## Implemented flow

Imports create dataset images with stable source names,
exact uploaded originals, SHA-256 provenance, local technical analysis, and an
import-first guided step.
The API generation path then treats those rows as a reference pool: it chooses
explicit references first, followed by reviewed imported photos ranked by
technical usefulness and spread across available framings. The generated row
stores both imported anchor ids and displayable anchor metadata.

The Corpus Workbench retains near-duplicates as reviewable groups, refreshes
technical analysis locally, and provides durable automatic, pinned, and
excluded anchor decisions. Exclusion is a provider-privacy decision, not a
training-set rejection.

The coverage planner uses framing plus angle, expression, lighting, pose,
background, and occlusion metadata. Optional Qwen/Ollama classification and the
manual editor write the same structured contract. It distinguishes covered,
weak, missing, and unknown states and preselects at most eight proven catalogue
gaps. An unclassified image remains unknown rather than an excuse to spend an
API call.

Only accepted (`keep`) rows count as training coverage. Generated candidates
store engine, prompt, catalogue gap ids, exact anchor descriptors and imported
anchor ids. Portable backup remaps row relationships when restored. Training
ZIPs remain standard image/text datasets and add a model-neutral provenance and
coverage manifest that ordinary trainers safely ignore.
