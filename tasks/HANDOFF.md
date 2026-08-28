# Implementation Handoff — Offline, No-Context Agents

Read this first. It assumes you know nothing about this project and have NO internet access.
Everything you need is on disk. If something you need is not listed here or in the two planning
documents, report BLOCKED with what is missing — do not improvise or fetch from the network.

## What this project is

`prep-my-avatar` is a heavily modified fork of the upstream project `lora-dataset-studio`.
It is a local Flask + React application for building LoRA training datasets (image import,
captioning, curation, training, and a ComfyUI-backed "Test Studio" for generating with trained
LoRAs). The current program ports selected upstream improvements into this fork. The plan is
`tasks/plan.md`; the task list with acceptance criteria is `tasks/todo.md`. Your task ID tells
you everything in scope; do not exceed it.

## Repository layout (the parts that matter)

- `backend/` — Flask app. Services in `backend/app/services/`, routes in `backend/app/routes/`,
  shared helpers in `backend/app/utils/`, tests in `backend/tests/`, ComfyUI workflow JSONs in
  `backend/workflows/`, DB migrations in `backend/app/__init__.py` (`_MIGRATIONS`, currently 1–17).
- `frontend/` — React (Vite, pnpm). Components in `frontend/src/components/`, pure utilities in
  `frontend/src/utils/`, hooks in `frontend/src/hooks/`. Generated output `frontend/dist/` is
  committed but ONLY the integration owner regenerates it — never rebuild or commit dist yourself.
- `src/avatar_prep/` + `tests/` — a standalone Python prototype that mirrors some backend logic.
- `tasks/upstream-evidence/` — see "Upstream evidence" below.
- `tasks/baseline-2026-08-28/` — the recorded clean baseline (all suites green at SHA `7cd3055d`).
  Any test failure you cause is yours; there are zero pre-existing failures.

## Environment — exact invocations

All commands run from the repo root unless stated. There is no internet; every dependency is
already installed. Do not run `pip install` or `pnpm install`.

- Python: `.venv/bin/python` (3.12.14). Tests: `.venv/bin/python -m pytest backend/tests/<file> -q`
- Lint: `.venv/bin/python -m ruff check <paths>`
- Frontend (always pnpm, never npm/yarn), run inside `frontend/`:
  - focused unit tests: `pnpm exec node --test src/utils/<file>.test.js`
  - lint/typecheck: `pnpm run lint`, `pnpm run typecheck`
  - full gate (integration owner only): `pnpm run gate`
- Node v22.21.1, pnpm 10.21.0, macOS arm64.

## Verification boundary (important)

You run ONLY the focused tests named in your task's Verification section, plus ruff on the files
you touched. The supervising orchestrator owns the full suites, `pnpm run gate`, e2e, and
checkpoints — never run them yourself, and never "fix" a failure in a file outside your task's
"Files likely touched" list; report BLOCKED instead.

## Upstream evidence (offline)

The full upstream clone is at `~/Documents/GitHub/lora-dataset-studio-upstream` (all cited
commits verified present). You should rarely need it: the relevant material is pre-extracted
into `tasks/upstream-evidence/`:

| File | Evidence for |
|---|---|
| `ST-studio-discovery-218d4b713.patch` | ST-03 family-aware Studio LoRA discovery |
| `ST-klein-studio-b6f64bd09.patch` | ST-05..ST-10 Klein lane, whitelists, honest refusal |
| `snapshot-7be0d068/flux2_klein_t2i.upstream.json` | ST-07 upstream Klein t2i graph (adapt, don't copy blind) |
| `snapshot-7be0d068/*.py`, `*.jsx` | upstream comfyui/klein helpers + tests at the reviewed snapshot |
| `CA-caption-authorship-945b26318.patch` | CA-01..CA-03 caption origin concept |
| `CA-author-labels-63b6f634c.patch` | CA-05..CA-07 API/UI author labels |
| `CA-manual-protection-14a2aedb2.patch` | CA-04, CA-08 asserted-caption protection |
| `QS-bokeh-sharpness-f1694e05a.patch` | QS-01..QS-03 tiled p90 Laplacian scoring |
| `LZ-stale-chunks-2df5becd4.patch` | LZ-01, LZ-02 one-shot lazy-chunk reload |
| `GA-*.patch`, `SV-*.patch`, `OR-openrouter-*.patch` | gated optional epics (not approved yet) |
| `comfyui-reference/folder_paths.py`, `extra_config.py`, `extra_model_paths.yaml.example` | ST-01: real ComfyUI model-root and `extra_model_paths.yaml` semantics |

The patches show what upstream did. This fork's architecture differs (services are split, the
five-family registry already exists at `backend/app/utils/training_families.py`); implement the
task's acceptance criteria in THIS fork's structure — a patch never applies cleanly and must not
be applied with `git apply`.

## Hard rules

1. pnpm only; never npm or yarn. Never touch `frontend/dist/`.
2. Never renumber, edit, or remove an existing migration; new migrations are additive and get
   their number at merge time (next is 18).
3. No silent fallback between model families, caption engines, or providers — unsupported
   requests fail with a named error.
4. Legacy caption rows keep `caption_origin = NULL`; NULL means "not recorded", never "machine".
5. No file outside your task's footprint. No pushes, PRs, issues, or version bumps.
6. No AI/assistant attribution anywhere: commits, comments, docstrings, or UI strings.
7. Commit messages are neutral and task-focused, e.g. `Add canonical ComfyUI model path resolver`.
8. If an acceptance criterion is ambiguous or contradicts the code you find, report BLOCKED with
   the exact file:line evidence — do not pick an interpretation silently.

## Known missing inputs (report BLOCKED if your task needs them)

- **QS-02 recalibration corpus:** the TRACKED corpus is `tasks/reference-corpus/` (four
  deterministic synthetic placeholders + `generate_corpus.py` + measured ground-truth README).
  `data/` is gitignored, so `data/reference-corpus/` is only a runtime copy that may be absent
  in a fresh worktree — regenerate or copy from `tasks/reference-corpus/`. Constants calibrated
  against placeholders are PROVISIONAL and must not be merged as release-ready; final constants
  require real, rights-cleared photographs via the operator gate. Never download images.
- **Live ComfyUI / GPU:** ST-10 and all live acceptance protocols require a running ComfyUI
  with real models. These are supervisor/operator gates, not agent work. The reproducible
  operator protocol, required assets, and evidence rules are in `tasks/ST-10-RUNBOOK.md`.

## Done report format

Return DONE with: commit SHA, files changed, commands run with results, manual checks not run,
and residual risks. Or BLOCKED with exact evidence. Nothing else.
