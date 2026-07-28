export const FRAMING_LABEL = { face: 'Face', bust: 'Bust', body: 'Body', back: 'Back' }
export const FRAMING_COLOR = {
  face: 'bg-indigo-400', bust: 'bg-violet-400', body: 'bg-sky-400', back: 'bg-slate-400',
}
export const DEFAULT_COVERAGE_TARGET = { face: 12, bust: 6, body: 6, back: 1 }
export const PRESET_META = [
  { key: 'balanced_25', name: 'Balanced', hint: 'The all-round default: every framing covered in training proportions.' },
  { key: 'zimage_12', name: 'Z-Image 12', hint: 'Compact 12-shot set tuned for Z-Image LoRA training.' },
  { key: 'balanced_multiformat', name: 'Multi-format', hint: 'Balanced set with landscape / vertical / cinema frames mixed in.' },
  { key: 'face_focused', name: 'Face-focused', hint: 'Face only (close-ups + busts, varied formats, no body shots) — body stays generic.' },
  { key: 'fullbody_focused', name: 'Full-body', hint: 'Reliable full-body: ~50/50 identity (face+bust) and full-body + back, varied formats.' },
  { key: 'body_emphasis', name: 'Body emphasis', hint: 'Body-fidelity pick with figure-revealing but API-safe outfits.' },
]
