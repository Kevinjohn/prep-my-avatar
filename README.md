# Prep My Avatar

Personal, noncommercial fork of [LoRA Dataset Studio](https://github.com/perfectgf/lora-dataset-studio),
focused on preparing a large, imperfect photo corpus before using generation
to fill specific coverage gaps.

The upstream application provides the guided workspace, curation, captioning,
training, export, setup, and documentation foundation. This fork changes the
front of the journey:

```text
large photo corpus → analyse → plan coverage → generate missing combinations → review → train/export
```

## Fork-specific workflow

- Import a large real-photo corpus while preserving every uploaded original byte,
  filename, SHA-256 digest, and normalized training derivative.
- Refresh technical quality locally and retain near-duplicates in explicit review
  groups; only byte-identical reimports are skipped.
- Map framing, angle, expression, lighting, pose, background, and occlusion with
  the optional local vision model or the manual Corpus Workbench editor.
- Separate the complete private reference pool from a bounded API anchor pack.
  Pin identity-critical images, leave selection automatic, or exclude an image
  from providers without removing it from training.
- Show covered, weak, missing, and unknown states. Unknown evidence never becomes
  an excuse for an API call.
- Preselect only proven catalogue gaps for Nano Banana or ChatGPT. Local Klein
  remains available when a primary reference is set.
- Keep imported and generated candidates together for curation while preserving
  engine, prompt, gap, anchor, source, and derivation provenance.
- Export ordinary image/text training pairs plus a model-neutral JSON manifest;
  portable backups retain originals, analysis, anchor decisions, coverage, and
  provenance.

The full corpus stays local. Only the visible bounded anchor pack is sent to an
API generation engine; images marked **Exclude** never enter that pack.

## Current application base

The forked application lives in the upstream layout:

- `backend/` — Flask application and dataset services
- `frontend/` — React workspace and guided UI
- `docs/guide/` — getting started, usage, troubleshooting, and help
- `docs/DATASET_GUIDE.md` — dataset-quality guidance
- `src/avatar_prep/` — the original prototype analysis library being migrated into the fork

See [`docs/specs/import-first-multi-reference-design.md`](docs/specs/import-first-multi-reference-design.md)
for the fork-specific architecture and data contracts.

## License and attribution

This is a personal, noncommercial project. See [`NOTICE.md`](NOTICE.md) and
[`LICENSE`](LICENSE) for attribution and license terms.
