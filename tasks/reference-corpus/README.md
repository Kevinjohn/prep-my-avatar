# Placeholder reference corpus

Four DETERMINISTIC SYNTHETIC PLACEHOLDERS (PIL, fixed seeds; generator recorded in session
notes) so the QS recalibration workflow can be exercised end to end offline. They are NOT a
valid final recalibration corpus: final score-mapping and admission constants must be
re-derived against real, rights-cleared photographs placed in this same directory.

## Measured ground truth (verified 2026-08-28 against the live pipeline)

| Image | v1 score (current) | v1 verdict | tiled p90 Laplacian var | tiled MAX |
|---|---:|---|---:|---:|
| `placeholder_bokeh_subject.jpg` | 34 | amber, "low sharpness" — **the false negative QS fixes** | 13.7 | 16.4 |
| `placeholder_uniform_blur.jpg` | 30 | amber, low sharpness (correct) | 1.5 | 1.7 |
| `placeholder_sharp.jpg` | 51 | green (correct) | 22.4 | 25.1 |
| `placeholder_blur_with_speck.jpg` | 32 | amber, low sharpness (correct) | 1.6 | **715.1** |

What this proves, per the plan's QS tasks:

- QS-01's precondition is reproducible: the current whole-frame scorer fails a genuinely
  sharp-subject/bokeh image (34) at nearly the same score as true uniform blur (30).
- Tiled p90 separates bokeh (13.7) from uniform blur (1.5) by ~9x, so the v2 contract is
  achievable: bokeh above the accepted boundary, uniform blur below.
- The speck image is why the plan mandates **p90, never max**: a single artifact tile drives
  tiled max to 715 (would falsely certify a blurred image as sharp) while p90 stays at 1.6.

p90/max reference figures were computed on the full-resolution image with a 3x3 Laplacian
(scipy prototype); the shipped QS-02 implementation runs on the analysis thumbnail per its
acceptance criteria, so expect the same ordering, not these exact values.

Images are tracked here (data/ is gitignored); data/reference-corpus/ is the runtime copy; regenerate with `.venv/bin/python tasks/reference-corpus/generate_corpus.py <outdir>`.
