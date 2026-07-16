# Using the app

The workspace is a **guided flow**: each stage stays folded until the one
before it is done, and the progress rail on the left tells you where you are
and what's blocking the next step. You never have to guess what comes next —
this chapter just explains what each stage does and where the useful buttons
hide.

---

## The character walkthrough (real corpus → trained LoRA)

1. **Create the dataset** — Datasets → New. Pick **Character**, name it, set a
   **trigger word** (the token your prompts will use), and choose the **target
   model** (Z-Image / SDXL / Krea 2 / FLUX.1 / FLUX.2 Klein — changes the caption
   style; you can change it later).
2. **Import the real corpus first.** Drag in as many useful photos as you have.
   Originals are preserved byte-for-byte and normalized derivatives keep their
   aspect ratio unless you explicitly enable head crop. Exact reimports are
   skipped; near-duplicates stay visible for review.
3. **Use the Corpus Workbench.** Refresh the local technical pass, then map
   framing, angle, expression, lighting, pose, background and occlusion with
   Ollama vision or the manual editor. Pin must-use identity anchors, leave good
   candidates on Automatic, and mark private/unsuitable provider references as
   Excluded. Excluded photos may still remain in the training set.
4. **Review the Coverage Plan.** It distinguishes covered, weak, missing and
   unknown evidence. Only accepted images count. Unknown means “classify or
   review this,” never “buy a generated replacement.”
5. **Optionally set a primary reference.** API engines can use the bounded
   corpus anchor pack directly. Local Klein still needs one primary reference;
   its crop editor and up to three explicit extra references remain available.
6. **Generate proven gaps only** — Nano Banana, ChatGPT or local Klein opens on
   the catalogue shots recommended by the plan. Every candidate records its
   engine, prompt, targeted gap and exact anchor pack.
7. **Curate** — keep / reject / crop, guided by the live meter targeting
   **12 face · 6 bust · 6 body · 1 back**. Watch the face-similarity badges
   (green = strong match, orange = review) to drop off-identity shots before
   they poison training.
8. **Caption** — one click captions the kept set (prose or booru tags,
   matched to the target model). The **identity-leak check** flags any caption
   that describes hair/face/skin — fix every flagged one. A find/replace +
   tag-frequency panel sweeps the whole set at once; its **💾 Write .txt
   files** button drops a kohya-style `<image>.txt` next to each kept image
   in the dataset folder (same format as the export ZIP) for external tools.
9. **Fix individual shots** — every generated tile has a ✏️ button: edit the
   exact prompt that made it and regenerate in place, without losing the rest.
10. **Train** — the pre-flight check runs the full checklist (count, balance,
   captions, leaks, duplicates). It no longer *blocks*: leaking captions and
   near-duplicates are editable right inside the confirm, and missing captions
   just ask you to **Start anyway** (captions stay strongly recommended). Steps
   are computed automatically; ⚙️ Advanced options exposes every knob (each with
   its own why/how) and a **Presets** row — apply a shipped ★ recipe (*Krea
   character*, *Concept*, *Style*) or save/import/export your own as a JSON.
   No GPU? **☁️ Train in cloud** rents one per run. Watch this run — and every
   other, cloud or local — from the **🏋️ Runs** tab, where you can retry a
   failed run (↻), continue a finished cloud run for more steps (▶), and download
   the LoRA.
11. **Pick the best checkpoint** — open the **Test Studio** from the dataset:
    grid-test checkpoint × strength, vote, rank by face similarity, and star ★
    the winning settings. The last checkpoint is almost never the best one.
12. **Export** — at any point, **Export ZIP** gives you standard image/text
    training pairs plus `_prep_my_avatar_manifest.json` with source mix,
    coverage and provenance. Trainers ignore the manifest; other tools can use
    it. Portable Backup additionally preserves exact originals and decisions.

## Concept datasets (an object or action, not a person)

Pick **Concept** at creation and describe the concept in the required field —
the captioner needs to know exactly *what to omit*. What changes vs character:

- **No reference photo.** Images come from **import** or the built-in
  **scraper** (paste a gallery URL or run a Reddit keyword search, tick the
  frames you want, they land straight in the dataset — deduplicated and
  quality-filtered). Already have a kohya-style dataset on disk (images +
  same-name `.txt` captions)? **⋯ More → 📂 Import from folder…** merges it in
  from a pasted folder path — captions attach, duplicates are skipped (a ZIP
  works too, via **📦 Import dataset**). On gallery sites (PornPics), a category/tag/search scan
  shows **the same previews the listing page does** — one per gallery, the shot
  that actually matches your keyword. Tick **Scan full albums** to pull every
  photo of each matched gallery instead, or paste a single `/galleries/…` URL
  to get that whole album. Sex.com works the same way for keyword searches
  (`sex.com/en/pics?search=…`) — every pin **is** a single matching image, so
  there is no album option to worry about. Civitai searches return **SFW
  results only** unless you add a Civitai API key in **Settings → Scraping &
  sources**.

  > **Reddit says "wait N seconds" (429)?** By default Reddit scans share a
  > public client id (and its ~1000 requests / 10 min quota) with many other
  > people, so it can be exhausted before your first scan. Add your own free
  > client ID in **Settings → Scraping & sources** — a one-minute, step-by-step
  > guide is built into that page.
- **Captions invert**: they describe everything *except* the concept, so the
  concept is what binds to the trigger. The leak check watches for stray
  descriptions of it.
- **Masked training is off** (a person mask would erase the very thing you're
  teaching), and imports keep the full frame instead of head-cropping.

## Style datasets (a global aesthetic)

Pick **Style** at creation. What changes:

- **No trigger word** — the style tints every image once the LoRA is loaded.
- **Captions describe content only** (never the rendering), and they're
  optional; caption dropout rises so the style generalizes.
- **Step count switches to a sublinear √n scale** built for the large sets
  (hundreds of images) style LoRAs want.

## Tips that save runs

- Trust the composition meter over your instinct — a set that "looks varied"
  is usually still face-heavy.
- Fix every leak the badge reports before training; one "a woman with long
  blonde hair" caption quietly competes with your trigger.
- Don't chase steps. Train the auto count, then let the Test Studio find the
  *earliest* checkpoint that nails the identity — it keeps the most prompt
  flexibility.
- The next chapter — **Building a good dataset** — explains *why* behind every
  rule above. Read it once before your first serious run.
