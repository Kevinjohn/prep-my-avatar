# ST-10 Runbook — Live FLUX.2 Klein Acceptance Gate

Committed, redacted operator runbook. Any operator following this document must be able to
reproduce the gate and reach the same pass/fail verdict.

## 1. Purpose

ST-10 live acceptance decides which FLUX.2 Klein variants (4B / 9B) may be advertised by this
app. Policy (approved 2026-08-28): the Klein variant list is an explicit allowlist — **only
variants that pass this live gate ship**. Supporting both 4B and 9B requires each to pass
independently. No variant is advertised on the strength of offline tests alone.

## 2. Environment record (fill in before first run — currently TBD)

| Item | Value |
|---|---|
| ComfyUI revision / commit | TBD |
| GPU model + VRAM | TBD |
| Driver / OS | TBD |
| Python version | TBD |
| torch version | TBD |
| ComfyUI launch command | TBD |
| `extra_model_paths.yaml` in effect | TBD (redacted copy or summary) |

## 3. Required assets

All assets must be present **before** any offline/tether session. Model weights are multi-GB
and must **never** be fetched over the tether. Hashes are TBD until first recorded; after that
they are the reference for every subsequent run.

| Asset | Filename | Folder type | SHA-256 | Source | Status |
|---|---|---|---|---|---|
| Klein 4B UNET | TBD | `unet` / `diffusion_models` | TBD | TBD | TBD |
| Klein 9B UNET (only if 9B is claimed) | TBD | `unet` / `diffusion_models` | TBD | TBD | TBD |
| Text encoder(s) | TBD | `text_encoders` / `clip` | TBD | TBD | TBD |
| VAE | TBD | `vae` | TBD | TBD | TBD |
| Klein LoRA deployed by this app (at least one) | TBD | `loras` | TBD | TBD | TBD |
| Extra-root copy of a Klein LoRA (for the extra-root test) | TBD | `loras` (extra root) | TBD | TBD | TBD |

## 4. Protocol

Fixed parameters (identical for every run and every variant):

- **Prompt (exact string):** `a plain gray ceramic mug on a wooden table, soft daylight`
- **Negative prompt:** empty
- **Seed:** `424242`
- **Dimensions:** `1024x1024`
- **Steps:** `20` (record the effective CFG the app applies)

Steps — repeat 1–9 **per advertised variant** (4B, then 9B if claimed):

1. Verify every asset in section 3 is present and hash-matches. Any missing or mismatched
   asset: the gate is **BLOCKED** for that variant. Do not download anything; stop.
2. **Strength 0 run (solo path):** queue a solo Klein generation with the fixed parameters and
   LoRA strength `0`. It must complete without ComfyUI errors and create a durable cell/row.
3. **Strength 1 run (solo path):** same parameters, LoRA strength `1`. Must complete and
   create a durable cell/row.
4. **Difference check (objective):** the strength-0 and strength-1 output images must differ
   (byte-compare or hash-compare the decoded images).
5. **Determinism check (objective):** rerun steps 2 and 3 once each. Same seed + same strength
   must reproduce identical outputs. Different-strength outputs must still differ.
6. **Comparison path:** run the comparison flow across strengths (0 vs 1) with the same fixed
   parameters. It must create durable cells for each leg; verify the captured graph JSON and
   queued job match the solo-path expectations.
7. **Cancel/resume:** start a run, cancel it mid-flight, then resume/re-queue. The resumed run
   must complete faithfully and reproduce the deterministic output for its seed/strength.
8. **Extra-root resolution:** run once using the LoRA served from the extra root. It must
   travel through picker, architecture resolution, payload, preflight, graph build, and the
   captured queue job unchanged, and produce the same deterministic output.
9. **Unsupported-family refusal:** attempt an unsupported FLUX family / missing asset /
   invalid base. Each attempt must produce **zero queued ComfyUI jobs and zero successful
   rows** — verify both the ComfyUI queue and the database.

Pass criteria per variant: all of 1–9 hold. A variant that fails any step is not advertised.

## 5. Evidence recording

- Root: `tasks/baseline-<date>/st10/` (e.g. `tasks/baseline-2026-08-28/st10/`).
- Per-run naming: `st10-<variant>-<step>-<strength>-run<N>.json` for captured graph/job JSON,
  same stem with `.log` for logs and `.png` for screenshots
  (e.g. `st10-4b-solo-s1-run2.json`).
- Capture for every run: the submitted graph JSON, output filenames and their hashes, the
  effective CFG, any ComfyUI errors verbatim, wall-clock timings, and screenshots of the
  resulting cells.
- Record the section 2 and section 3 tables (with hashes filled in) alongside the runs.
- **Redaction rule:** no absolute personal paths (write `<models-root>/...`,
  `<extra-root>/...`) and no tokens, keys, or credentials anywhere in committed evidence.

## 6. Connectivity policy

- Once section 3 assets are present and hash-verified, the gate runs **fully offline**.
- Only API-model calls (orchestration) may use the tether; no gate step depends on them.
- Any missing asset means the gate is **BLOCKED** — assets are never downloaded mid-gate,
  over tether or otherwise. Fix the asset inventory in a separate provisioning session, then
  restart the gate from step 1.
