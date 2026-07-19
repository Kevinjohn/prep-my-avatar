import{j as e,q as k,m as j,r as T,L as w}from"./index-CMsFUl10.js";import{D as N}from"./DiagnosticReport-BuAyo-71.js";function p(a,r="i"){const i=[],t=/(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)|(\[[^\]]+\]\([^)]+\))/g;let s=0,o,d=0;for(;(o=t.exec(a))!==null;){o.index>s&&i.push(a.slice(s,o.index));const n=o[0],c=`${r}-${d++}`;if(n.startsWith("`"))i.push(e.jsx("code",{className:"px-1 py-0.5 rounded bg-surface-raised text-indigo-200 text-[0.8125em] font-mono",children:n.slice(1,-1)},c));else if(n.startsWith("**"))i.push(e.jsx("strong",{className:"text-content font-semibold",children:n.slice(2,-2)},c));else if(n.startsWith("*"))i.push(e.jsx("em",{children:n.slice(1,-1)},c));else{const h=n.match(/^\[([^\]]+)\]\(([^)]+)\)$/);i.push(e.jsx("a",{href:h[2],target:"_blank",rel:"noreferrer",className:"text-indigo-300 underline decoration-indigo-400/40 hover:decoration-indigo-300",children:h[1]},c))}s=o.index+n.length}return s<a.length&&i.push(a.slice(s)),i}function S(a){const r=a.replace(/\r\n/g,`
`).split(`
`),i=[];let t=0;for(;t<r.length;){const s=r[t];if(!s.trim()){t++;continue}if(s.startsWith("```")){const n=[];for(t++;t<r.length&&!r[t].startsWith("```");)n.push(r[t++]);t++,i.push({t:"code",body:n.join(`
`)});continue}const o=s.match(/^(#{1,3})\s+(.*)$/);if(o){i.push({t:`h${o[1].length}`,body:o[2]}),t++;continue}if(/^(-{3,}|\*{3,})\s*$/.test(s)){i.push({t:"hr"}),t++;continue}if(s.startsWith(">")){const n=[];for(;t<r.length&&r[t].startsWith(">");)n.push(r[t++].replace(/^>\s?/,""));i.push({t:"quote",body:n.join(" ")});continue}if(/^\|/.test(s)){const n=[];for(;t<r.length&&/^\|/.test(r[t]);)n.push(r[t++]);const c=m=>m.replace(/^\||\|$/g,"").split("|").map(l=>l.trim()),h=c(n[0]),u=n.slice(2).map(c);i.push({t:"table",header:h,body:u});continue}if(/^(\s*)([-*]|\d+\.)\s+/.test(s)){const n=[],c=/^\s*\d+\./.test(s);for(;t<r.length&&/^(\s*)([-*]|\d+\.)\s+/.test(r[t]);){let h=r[t].replace(/^(\s*)([-*]|\d+\.)\s+/,"");for(t++;t<r.length&&/^\s{2,}\S/.test(r[t])&&!/^(\s*)([-*]|\d+\.)\s+/.test(r[t]);)h+=" "+r[t++].trim();n.push(h)}i.push({t:"list",ordered:c,items:n});continue}const d=[s];for(t++;t<r.length&&r[t].trim()&&!/^(#{1,3}\s|```|\||>|(\s*)([-*]|\d+\.)\s|-{3,}\s*$)/.test(r[t]);)d.push(r[t++]);i.push({t:"p",body:d.join(" ")})}return i}const x=a=>String(a||"").replace(/[`*_]/g,"").toLocaleLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"");function y(a,r,i=!1){const t=`b${r}`;switch(a.t){case"h1":return e.jsx("h1",{className:"m-0 mt-2 text-content font-bold text-2xl",children:p(a.body,t)},t);case"h2":return e.jsx("h2",{id:i?void 0:x(a.body),className:`${i?"text-xl":"mt-4 border-b border-border pb-1.5 text-lg"} m-0 scroll-mt-24 text-content font-bold`,children:p(a.body,t)},t);case"h3":return e.jsx("h3",{className:"m-0 mt-2 text-content font-semibold text-base",children:p(a.body,t)},t);case"hr":return e.jsx("hr",{className:"border-border my-2"},t);case"quote":return e.jsx("blockquote",{className:"m-0 rounded-lg border border-indigo-400/40 bg-indigo-500/10 px-4 py-3 text-content text-sm leading-relaxed",children:p(a.body,t)},t);case"code":return e.jsx("pre",{tabIndex:0,className:"m-0 rounded-lg border border-border bg-app/60 p-3 overflow-x-auto text-[0.8125rem] text-content-muted font-mono",children:a.body},t);case"table":return e.jsx("div",{className:"overflow-x-auto rounded-lg border border-border",children:e.jsxs("table",{className:"w-full text-sm border-collapse",children:[e.jsx("thead",{children:e.jsx("tr",{className:"bg-surface-raised",children:a.header.map((s,o)=>e.jsx("th",{className:"text-left px-3 py-2 text-content font-semibold border-b border-border whitespace-nowrap",children:p(s,`${t}h${o}`)},o))})}),e.jsx("tbody",{children:a.body.map((s,o)=>e.jsx("tr",{className:o%2?"bg-surface":"",children:s.map((d,n)=>e.jsx("td",{className:"px-3 py-2 text-content-muted align-top border-b border-border last:border-b-0",children:p(d,`${t}r${o}c${n}`)},n))},o))})]})},t);case"list":{const s=a.ordered?"ol":"ul";return e.jsx(s,{className:`m-0 flex flex-col text-sm text-content-muted ${i&&a.ordered?"list-none gap-2 p-0":`gap-1.5 pl-5 ${a.ordered?"list-decimal":"list-disc"}`}`,children:a.items.map((o,d)=>{const n=o.match(/^\[([ xX])\]\s+(.*)$/);return n?e.jsxs("li",{className:"list-none -ml-5 flex items-start gap-2",children:[e.jsx("span",{"aria-hidden":!0,className:`mt-0.5 grid place-items-center w-4 h-4 shrink-0 rounded border text-[0.625rem] ${n[1]===" "?"border-border-strong text-transparent":"border-emerald-400/60 bg-emerald-500/15 text-emerald-300"}`,children:"✓"}),e.jsx("span",{children:p(n[2],`${t}i${d}`)})]},d):i&&a.ordered?e.jsxs("li",{className:"flex gap-3 rounded-lg border border-border bg-app px-3 py-3 leading-relaxed",children:[e.jsx("span",{"aria-hidden":!0,className:"grid h-6 w-6 shrink-0 place-items-center rounded-md bg-indigo-500/15 font-mono text-[0.6875rem] font-bold text-indigo-300",children:String(d+1).padStart(2,"0")}),e.jsx("span",{children:p(o,`${t}i${d}`)})]},d):e.jsx("li",{children:p(o,`${t}i${d}`)},d)})},t)}default:return e.jsx("p",{className:"m-0 text-sm text-content-muted leading-relaxed",children:p(a.body,t)},t)}}function I({source:a,variant:r="default"}){const i=S(a||"");if(r==="guide"){const t=i.filter((n,c)=>!(c===0&&n.t==="h1")),s=[],o=[];let d=null;return t.forEach((n,c)=>{n.t==="h2"?(d={heading:n,blocks:[],index:c},o.push(d)):d?d.blocks.push({block:n,index:c}):n.t!=="hr"&&s.push({block:n,index:c})}),e.jsxs("div",{className:"flex max-w-none flex-col gap-4",children:[s.length>0&&e.jsx("div",{className:"flex flex-col gap-3 rounded-xl border border-indigo-400/20 bg-gradient-to-br from-indigo-500/10 via-surface to-surface px-4 py-4 sm:px-5",children:s.map(({block:n,index:c})=>y(n,c,!0))}),o.map(({heading:n,blocks:c,index:h})=>e.jsxs("section",{id:x(n.body),className:"scroll-mt-24 rounded-xl border border-border bg-surface px-4 py-4 shadow-sm shadow-black/10 sm:px-5 sm:py-5",children:[e.jsxs("div",{className:"mb-4 flex items-start gap-3 border-b border-border pb-3",children:[e.jsx("span",{"aria-hidden":!0,className:"mt-1 h-5 w-1 shrink-0 rounded-full bg-gradient-primary"}),y(n,h,!0)]}),e.jsx("div",{className:"flex flex-col gap-3",children:c.map(({block:u,index:m})=>y(u,m,!0))})]},`section-${h}`))]})}return e.jsx("div",{className:"flex max-w-none flex-col gap-3",children:i.map((t,s)=>y(t,s))})}const L=`# Getting started

Prep My Avatar turns a real photo corpus into a trained, ranked LoRA —
curation, captioning, face-scoring and training behind a single browser tab, on
your own machine. The useful part of LoRA training isn't the training; it's
building a clean, balanced, well-captioned image set. This app puts that whole
pipeline behind one UI.

> **In a hurry?** Launch the app, let the **Setup** wizard scan your machine,
> and create your first dataset from your own photos — no API key, no GPU, no
> external tool required for that first step.

---

## Two ways to run it

| | API-only | Full local |
|---|---|---|
| **What works** | Create datasets, generate via Gemini/ChatGPT, curate, caption via API, export ZIP | Everything — plus local (Klein) generation, JoyCaption, face scoring, masks, training, Test Studio |
| **Needs** | Python 3.10–3.12, an API key | ComfyUI and/or ai-toolkit + an NVIDIA GPU (12 GB+ for local generation) |
| **Good for** | Laptops, first try, cloud training | The full pipeline on a training rig |

You can start API-only and add the local tools later — features light up
automatically when their tool is detected.

## First launch

**Windows (one command):** clone the repo, then run \`start.bat\`. It picks a
ML-compatible Python (3.11–3.12), creates a \`.venv\`, installs the requirements and
opens the app at \`http://127.0.0.1:5050/\`.

**Any OS (manual venv):**

\`\`\`
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\\Scripts\\activate
pip install -r backend/requirements.txt
python backend/run.py
\`\`\`

**Docker (API-only):** \`cp .env.example .env\`, set \`LDS_ACCESS_TOKEN\` in \`.env\`
to a long random value, then run \`docker compose up --build\`. Open
\`http://127.0.0.1:5050/remote-login\` and enter that token.

The full install matrix (portable bundle, GPU requirements, external tools)
lives in the README on GitHub.

## The Setup wizard

On first launch you land in **Setup**. It scans your machine automatically and
walks through five steps — each one unlocks a set of features:

1. **Image generation** — add a Gemini or OpenAI API key (or point at a local
   Klein model) so the app can generate dataset images.
2. **ComfyUI** — unlocks local (Klein) generation and the Test Studio.
3. **Ollama** — the local vision model behind auto-captioning, six-axis corpus
   coverage mapping and head-crop.
4. **Quality tools** — face-similarity scoring and person masks (a one-click
   \`pip install\`).
5. **ai-toolkit** — the training engine.

Nothing is mandatory: **Skip setup** is always available, and every step can be
revisited later from **Settings**, where each tool has a Test button that tells
you immediately whether the app can see it.

## Around the app

- **Datasets** — the home tab and your **library**: photo tiles of every
  dataset, grouped by model family, with a search box and a badge for each
  family you've already trained. Create one and work it through the guided
  flow (source → curate → caption → train).
- **🏋️ Runs** — every training in one place, cloud *and* local: live progress,
  the settings each launch used, retry a failed run (↻), continue a finished
  one (▶), and download the LoRA (appears once ai-toolkit or a vast.ai key is set).
- **Test Studio** — grid-test a trained LoRA across checkpoints and strengths,
  vote, and rank (appears once ComfyUI is reachable).
- **Guide** — this manual.
- **Setup** — the guided wizard, re-runnable anytime.
- **Settings** — everything the wizard configures, plus server, updates,
  maintenance and the diagnostic report.

Next chapter: **Using the app** — the full walkthrough, dataset type by dataset
type.
`,A=`# Using the app

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
   Ollama vision or the manual editor. Imports start at **Needs decision** and
   do not train until you explicitly Accept them. Run **Analyze faces** after
   setting a reference: face-region sharpness/exposure and identity are recorded
   alongside whole-image quality. Pin several strong, accepted identity anchors, leave good
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
   For irreplaceable low-quality evidence, open it at full size and choose
   **Reconstruct & compare**. This is a generative, identity-constrained repair,
   not neutral upscaling. Curation shows source and candidate side by side with
   measured quality/identity deltas and atomically admits one version or neither.
8. **Caption** — one click captions the kept set (prose or booru tags,
   matched to the target model). The **identity-leak check** flags any caption
   that describes hair/face/skin — fix every flagged one. A find/replace +
   tag-frequency panel sweeps the whole set at once; its **💾 Write .txt
   files** button drops a kohya-style \`<image>.txt\` next to each kept image
   in the dataset folder (same format as the export ZIP) for external tools.
9. **Fix individual shots** — every generated tile has a ✏️ button: edit the
   exact prompt that made it and regenerate in place, without losing the rest.
10. **Train** — the pre-flight check runs the full checklist (count, balance,
   captions, leaks, duplicates, pixel/identity QA, watermarks, enlarged crops,
   reconstruction provenance, source rights and real/generated source mix). Most findings warn;
   an impossible double-kept reconstruction pair blocks until resolved. Leaking captions and
   near-duplicates are editable right inside the confirm, and missing captions
   just ask you to **Start anyway** (captions stay strongly recommended). Steps
   are computed automatically; ⚙️ Advanced options exposes every knob (each with
   its own why/how) and a **Presets** row — apply a shipped ★ recipe (*Krea
   character*, *Concept*, *Style*) or save/import/export your own as a JSON.
   No GPU? **☁️ Train in cloud** rents one per run. Watch this run — and every
   other, cloud or local — from the **🏋️ Runs** tab, where you can retry a
   failed run (↻), continue a finished cloud run for more steps (▶), and download
   the LoRA. At admission, the app makes an immutable training snapshot and
   hashes its files and recipe. If the dataset changes while that snapshot is
   being captured, launch stops cleanly instead of training a mixed revision.
11. **Pick the best checkpoint** — open the **Test Studio** from the dataset:
    grid-test checkpoint × strength with fixed seeds, vote, rank by face
    similarity, and star ★ the winning settings. Results link to the exact
    training-run record—not a filename guess—so the feedback panel can compare
    recipes, suggest an earlier step or strength, and recommend a controlled
    next iteration. The last checkpoint is almost never the best one.
12. **Export** — at any point, **Export ZIP** gives you standard image/text
    training pairs plus \`_prep_my_avatar_manifest.json\` with source mix,
    coverage and provenance. Trainers ignore the manifest; other tools can use
    it. Portable Backup additionally preserves exact originals and decisions.

## Privacy, recovery and operational safety

- **Remote generation is off by default.** Enable it explicitly in **Settings →
  Image engines → Remote-generation privacy** before Nano Banana or ChatGPT can
  receive prompts or the bounded reference pack. Local Klein stays on-device.
  Record source rights and identifiable-person consent in the Corpus Workbench;
  publishing to Hugging Face requires a separate confirmation.
- **Curation is reversible.** Use the curation-history control to undo recent
  keep/reject changes. Deleting a dataset, checkpoint, cloud staging directory,
  or deployed LoRA moves it to **Settings → Maintenance → Trash**; restore it
  there before choosing **Empty trash**, which is the permanent step.
- **Portable backup is the move/copy format.** It creates a new dataset when
  restored and carries originals, normalized files, captions, settings,
  relationships, decisions and provenance. A training ZIP is deliberately
  smaller and is not a complete backup.
- **Integrity checking is read-only.** Run **Settings → Maintenance → Data
  integrity** to inspect SQLite consistency, relationships, referenced files,
  unsafe links and untracked files without modifying the dataset.
- **Cloud safeguards are launch boundaries, not a provider bill.** The maximum
  hourly price, concurrency limit and monthly budget can block a new launch;
  runtime/stall timeouts terminate unhealthy runs. The Runs page shows measured
  billing time and cost, but the provider console remains authoritative.
- **Updates are transactional for clean Git checkouts.** The in-app updater
  accepts fast-forwards only, installs pinned dependencies, verifies isolated
  startup and the committed frontend build, then restarts. A failed or
  interrupted update keeps a private recovery journal and restores the previous
  revision; it refuses an automatic reset if local work appeared meanwhile.
- **LAN access is authenticated by default.** Turning on **Available on the
  local network** requires an access token unless you explicitly disable it.
  The token is entered on the remote login page and never embedded in a URL or
  QR code. Loopback access remains local-only and token-free.

## Concept datasets (an object or action, not a person)

Pick **Concept** at creation and describe the concept in the required field —
the captioner needs to know exactly *what to omit*. What changes vs character:

- **No reference photo.** Images come from **import** or the built-in
  **scraper** (paste a gallery URL or run a Reddit keyword search, tick the
  frames you want, they land straight in the dataset — deduplicated and
  quality-filtered). Already have a kohya-style dataset on disk (images +
  same-name \`.txt\` captions)? **⋯ More → 📂 Import from folder…** merges it in
  from a pasted folder path — captions attach, duplicates are skipped (a ZIP
  works too, via **📦 Import dataset**). On gallery sites (PornPics), a category/tag/search scan
  shows **the same previews the listing page does** — one per gallery, the shot
  that actually matches your keyword. Tick **Scan full albums** to pull every
  photo of each matched gallery instead, or paste a single \`/galleries/…\` URL
  to get that whole album. Sex.com works the same way for keyword searches
  (\`sex.com/en/pics?search=…\`) — every pin **is** a single matching image, so
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
`,R=`# Building a good LoRA dataset

This guide condenses what actually moves the needle when training a character LoRA
with this app (ai-toolkit under the hood). Every number here matches what the app
enforces or defaults to — when in doubt, the app's warnings are this guide applied.

> **The one principle behind everything:** a LoRA learns whatever is **constant
> across your images and NOT described in the captions**. Keep the subject constant,
> vary everything else, and never describe the subject — that's the trigger word's job.

---

## 1. Pick your model family first

The family changes the caption style, the image count, and the settings — so decide
before you caption anything.

| | Z-Image | SDXL | Krea 2 | FLUX.1 | FLUX.2 Klein |
|---|---|---|---|---|---|
| **Caption style** | Prose sentences | Booru tags | Prose sentences | Prose sentences | Prose sentences |
| **Images (min → good)** | 12 → 20+ | 20 → 30+ | 15 → 20+ | 15 → 20+ | 15 → 20+ |
| **Training base** | Z-Image-Turbo (or a converted custom merge) | Your ComfyUI checkpoint (e.g. bigLove) | Krea-2-Raw (default) or Turbo | FLUX.1-dev (gated HF) | FLUX.2-klein-base 4B (default) or 9B (gated HF) |
| **Preview quality** | Fast, distilled | Depends on checkpoint | Raw: slow but faithful | High, ~20 steps | Non-distilled, real CFG (~25 steps) |
| **Best for** | Fast iteration, prose-driven prompting | Booru-native checkpoints, NSFW ecosystems | Highest realism ceiling | The largest LoRA ecosystem, strong prompt fidelity | Modern FLUX.2 stack; 4B trains on mid-range GPUs |

**Krea note:** the default trains on **Krea-2-Raw** — the official recommendation is
*"train on Raw, validate on Turbo"*. Raw runs are long (hours); that's normal, not stuck.

**FLUX.1 note:** trains on **FLUX.1-dev**, a *gated* Hugging Face model — accept its
license and set a HF token before the first run (the initial download is ~24 GB). It's
a 12B model like Krea 2, so **~24 GB VRAM** is the comfort zone (drop the resolution to
**768** to fit smaller cards). **Local training only for now**; in-app testing (Test
Studio) is coming — until then, test your Flux LoRA in your own ComfyUI.

**FLUX.2 Klein note:** two model sizes, picked next to the base selector — **4B**
(default) trains on a **16–24 GB** local GPU, **9B** needs **32–48 GB VRAM** and is
best trained via **☁️ Train in cloud** (both local and cloud runs are supported for
this family). Both bases are *gated* on Hugging Face: accept the license of
\`FLUX.2-klein-base-4B\` / \`-9B\` and set a HF token before the first run. In-app
testing (Test Studio) is coming — until then, test your Klein LoRA in your own
ComfyUI.

---

## 2. How many images, and which ones

- **Target ~25 images** for a balanced character LoRA. More isn't automatically
  better — 25 varied images beat 60 near-duplicates every time.
- **Balance the framing.** The app tracks four buckets: **face / bust / body / back**.
  A dataset that is 100% face close-ups produces a LoRA that falls apart on
  full-body prompts — it has never seen the body.
- **Vary everything except the person:** location, lighting, outfit, pose,
  expression, camera angle. Whatever repeats across images gets baked into the
  LoRA — a repeated background wall becomes part of "the person".
- **Reject near-duplicates.** Two frames of the same shot teach nothing and
  overweight that look. The pre-flight check flags them; reject one of each pair.
- **Quality floor:** no motion blur, no heavy compression, the face readable.
  One bad image does more harm than one good image does good.

### Preserve first, admit second

For character datasets, an import now enters the **master corpus** as *Needs
decision*. It is preserved, analysed and available for coverage review, but it
does not train until you explicitly **Accept** it. Run both local technical
analysis and face analysis first. The latter measures the detected face crop —
sharpness, exposure, detection confidence, size, pose, face count and identity
similarity — rather than letting a crisp background disguise a soft face.

Pin several strong, accepted photos with different angles and expressions. The
face scorer uses the primary/additional references plus up to four pinned photos
as a small identity centroid, which is more reliable than one reference frame.

### What “upscaling” can and cannot fix

- Ordinary resizing can create more pixels, but not new evidence. A 400 px face
  enlarged to 1024 px is still a 400 px face; the app flags heavily enlarged
  crops in pre-flight.
- Blur, missed focus, clipped highlights and heavy compression are usually reasons
  to prefer another photo. Restoration has diminishing returns quickly.
- **Reconstruct & compare** is explicitly generative. It starts from the exact
  preserved upload, adds reviewed identity references and measures technical and
  identity deltas. It never overwrites the source, and its side-by-side resolver
  allows exactly one version — source, reconstruction, or neither — into training.
- Treat a reconstruction as a last-resort replacement for unique evidence, not as
  a way to double the dataset. Inspect eyes, teeth, hairline, skin texture and small
  identity marks at 100%; prefer the source when the measured gain is absent or
  identity similarity falls.

**Body fidelity mode** (Datasets → ⋯ More): use it when the body shape and body
marks (tattoos, scars) should bind to the trigger too. It shifts the composition
targets toward bust/body shots, imports full-frame by default, and extends the
caption rules below to body marks.

---

## 3. Captions — the make-or-break step

The model reads your captions during training and learns to attribute **whatever
the caption does NOT explain** to the trigger word.

**The golden rule: never describe what the person IS — describe everything else.**

- ❌ \`myTrigger, a woman with long blonde hair and blue eyes, smiling\` —
  the LoRA learns almost nothing: the caption already "explains" the appearance.
- ✅ \`myTrigger, sitting at a café table, warm afternoon light, denim jacket,
  looking at the camera\` — hair, face and skin are unexplained → they bind
  to \`myTrigger\`.

Concretely:

1. **Start every caption with the trigger word.** The app injects it on export.
2. **Never mention hair, face, eyes or skin.** The app's *identity-leak* check
   flags captions that do — fix every flagged one before training.
3. **Describe scene, outfit, pose, lighting, framing.** Those are the things you
   want to stay promptable *independently* of the identity.
4. **Vary the captions.** Identical captions across images teach nothing;
   captions under ~8 words are too weak to isolate the identity.
5. **Match the style to the family.** Prose for Z-Image and Krea; booru tags for
   SDXL booru-native checkpoints. The app blocks a mismatch for a reason —
   a prose-captioned SDXL LoRA produces disjointed images.

**Concept datasets** (training a *thing/style/act*, not a person) invert the rule:
describe everything **except the concept** — the concept is what must bind to the
trigger. Keep masked training **off** for concepts (a person mask would erase the
very thing you're training).

---

## 4. Settings cheat-sheet

The defaults below are the app's defaults (post-research). Change them from
⚙️ Advanced options on the training panel — each knob has its own why/how there.
That panel also has a **Presets** row: apply a shipped ★ recipe (*Krea
character*, *Concept*, *Style*), or save your tuned settings as a named preset to
reuse across datasets and share (import/export as JSON).

| Setting | Z-Image | SDXL | Krea 2 | FLUX.1 | FLUX.2 Klein | Why |
|---|---|---|---|---|---|---|
| **LoRA rank / alpha** | 16 / 16 | 32 / 16 | 32 / 32 | 16 / 16 | 16 / 16 | Capacity to memorize the identity. SDXL's alpha = rank ÷ 2 is that family's half-strength convention. |
| **Resolution** | 768 + 1024 | 768 + 1024 | 768 + 1024 | 768 + 1024 | 768 + 1024 | Multi-scale: holds up from close-up to full-body. |
| **Save checkpoint** | every 250 | every 250 | every 250 | every 250 | every 250 | More snapshots → better odds one is at the sweet spot. |
| **Steps** | auto | auto | auto | auto | auto | ~120 × images, clamped 1500–3500. A fixed 3000 overcooks small sets. |
| **Masked training** | ON | ON | ON | ON | ON | Background weighs only 10% of the loss → identity binds to the person, not the room. OFF for concepts. |

Rules of thumb:

- **Raise rank (48–64)** only for a hard identity (distinctive features the
  default misses) *and* a bigger dataset — high rank on 15 images just memorizes them.
- **Don't chase steps.** More steps past the sweet spot = overfitting (plastic
  skin, same face angle everywhere, prompt deafness). Train with checkpoints
  every 250 and pick the best one instead.
- **Turbo variant (Krea)** is the VRAM/time-friendly fallback — fine for drafts,
  Raw for the final run.
- **GPU under 24 GB?** Resolution is the #1 memory lever: set it to **768 only**
  (Krea 2 especially — 1024 saturates a 24 GB card). You trade some fine detail
  for a run that actually fits and trains far faster.

### Steps — how many, and where "good results" start

The app sets the step count **automatically** for a character LoRA:
**≈ 120 × kept images, clamped to 1500–3500.** The *target is the same* for
Z-Image, SDXL, Krea 2, FLUX.1 and FLUX.2 Klein — the model family changes how *fast*
that target converges, not the number. (Concept/style datasets scale differently:
**475 · √n, clamped 2000–12000**, because they train on hundreds of images.)

So the character step count just follows your dataset size:

| Kept images | Auto steps |
|---|---|
| 12–15 | 1500 – 1800 |
| 20 | 2400 |
| 25 | 3000 |
| 30 and up | 3500 (capped) |

**"Good results" is a checkpoint you pick, not the finish line.** A snapshot is
saved every 250 steps, and the best one is almost never the last — later
checkpoints know the face better but obey prompts worse. *Where* the first
usable checkpoint appears depends on how fast the model converges:

| Model | Converges | Where the sweet spot tends to land |
|---|---|---|
| **Z-Image** | Fast (distilled) | Around the **middle** of the run; watch for overfit in the last ~20% (waxy skin, frozen expression) |
| **Krea 2 – Turbo** | Fast (distilled) | Like Z-Image — check early-to-middle checkpoints first |
| **SDXL** | Medium (base-dependent) | Middle of the run; booru-native checkpoints lock an identity quickly |
| **Krea 2 – Raw** | Slow (12B, non-distilled) | The **last third** — the run is long by design, let it finish the full count rather than stopping early |
| **FLUX.1-dev** | Medium (12B, guidance-distilled) | Middle of the run; a strong prompt-follower, so watch for waxy skin / frozen expression if you overshoot into the last ~20% |
| **FLUX.2 Klein (4B/9B)** | Medium (non-distilled base) | Middle of the run; previews run with real CFG so overfit shows honestly — pick the earliest checkpoint that holds the identity |

**Takeaway:** don't hand-tune the step number. Train the auto count, then use the
**Test Studio** to pick the *earliest* checkpoint that nails the identity — that's
the one with the most prompt flexibility left.

---

## 5. Pre-flight checklist

The app runs these checks when you hit Train — here's the list to self-check earlier:

- [ ] At least the family minimum kept (12 Z-Image / 20 SDXL / 15 Krea / 15 FLUX.1 / 15 FLUX.2 Klein) — 20–30 is the comfort zone
- [ ] Framing balanced — not 100% face shots (some bust/body/back)
- [ ] Every kept image captioned *(strongly recommended — a blank caption won't block the launch, it just asks you to confirm "train anyway")*
- [ ] **Zero identity leaks** (no hair/face/skin words — the leak badge shows 0)
- [ ] Captions varied, ≥ 8 words, style matches the family (prose vs booru)
- [ ] Near-duplicate pairs resolved (keep one of each)
- [ ] No red technical/face-region QA among accepted images
- [ ] Identity checked; multi-face and low-similarity frames reviewed manually
- [ ] No unresolved watermark or reconstruction review
- [ ] No heavily enlarged crop being mistaken for native detail
- [ ] Real photographs remain the majority; generated/reconstructed images only fill gaps
- [ ] Body fidelity: if ON, actual full-body shots exist

---

## 6. After training: pick the right checkpoint

Training produces a checkpoint every 250 steps — **the last one is often NOT the
best one**. Later checkpoints know the identity better but obey prompts worse.

1. Open the **Test Studio** from the dataset (the LoRA comes pre-selected).
2. Generate the same prompt grid across several checkpoints and strengths.
3. Pick the **earliest checkpoint that nails the identity** — it keeps the most
   prompt flexibility. Signs you've gone too far: waxy skin, identical
   expression/angle regardless of prompt, outfits from the dataset bleeding in.
4. Save the winning settings (★) — they're reused as the dataset's defaults.

---

*Everything above is enforced or surfaced by the app itself (pre-flight checks,
leak badge, composition bar, advanced options). This page just explains why.*
`,C=`# Troubleshooting

Symptom-first, most-reported first. If your problem isn't here, the next
chapter (**Getting help**) shows how to report it with one click.

---

## "No Z-Image model available" in the Test Studio or training panel

**Why:** the Test Studio generates through ComfyUI, so the Z-Image *base model*
must physically live in your ComfyUI install — and the scanner only accepts it
inside a sub-folder whose name contains \`z image\` (or \`zimage\`). A file dropped
loose in \`models/unet\` is **not** detected.

**Fix:** lay the stack out like this inside your ComfyUI folder, then re-test:

\`\`\`
models/unet/z image/<your Z-Image checkpoint>.safetensors
models/text_encoders/Z image/qwen_3_4b.safetensors
models/vae/z ae.safetensors
\`\`\`

A Z-Image LoRA only works on a Z-Image base — a regular SD/SDXL graph
(20–30 steps, CFG 7) renders garbage; Z-Image-Turbo wants euler / simple /
**8 steps / CFG 1.0** (the app's workflows already do this).

## "No SDXL checkpoint found" on a fresh install

**Why:** the app derives the models folder from **Settings → Local tools →
ComfyUI install directory**. If only the API URL is set, there's nothing to scan.

**Fix:** point the install directory at the folder that contains \`models/\` and
\`main.py\` (the Setup wizard detects it for you), then hit **Test**. SDXL
checkpoints are scanned from \`models/checkpoints\`.

## The reference crop isn't centered on the face

**Why:** on a fresh clone the configured Ollama vision model isn't pulled yet,
so head detection silently falls back to a centered square crop. The app now
shows a warning toast naming the missing model when this happens.

**Fix:** **Setup → Ollama** — pull the vision model (use the **Instruct**
variant, not *Thinking*), or click the tile's crop button and frame it by hand.
**↺ Reset to auto** re-runs the auto-crop after the model is installed.

## Training log looks frozen for several minutes

**Why:** ai-toolkit's output is block-buffered during model load and latent
caching — nothing prints even though it's working. A "warming up" phase before
the first logged step is expected, and Krea-2-Raw runs are *hours* long by
design.

**Fix:** nothing to fix — check GPU utilization or watch the ai-toolkit output
folder for new files if you want proof of life. The cloud runs page has a
stall watchdog that kills genuinely stuck runs.

## ai-toolkit isn't detected (conda / uv / no venv)

**Why:** the app auto-detects ai-toolkit's Python from a \`venv/\` or \`.venv/\`
folder next to its \`run.py\`. Installs that use conda, uv or the system Python
have no such folder, so the Test button can't find an interpreter — training
and JoyCaption stay hidden.

**Fix:** in **Settings → Local tools → ai-toolkit**, keep the directory pointing
at the ai-toolkit folder and fill the optional **Python interpreter** field with
the full path to the python that has ai-toolkit's dependencies (e.g.
\`C:\\miniconda3\\envs\\aitk\\python.exe\`), then hit **Test**. ComfyUI Desktop installs
are recognized automatically — no extra step.

## Reddit scan says "rate limiting requests, retry in Ns" (429)

**Why:** out of the box, Reddit scans authenticate with a **public client id
shared by many people** (the gallery-dl one). Reddit's quota — about 1000
requests per 10-minute window — is attached to that id, so other users can
exhaust it before your very first scan of the day. The "retry in Ns" number is
just the time left in the current 10-minute window.

**Fix:** get your own free client ID (one minute, no app secret involved):
**Settings → Scraping & sources** has the field plus a built-in step-by-step
guide. The one trap: on reddit.com/prefs/apps, pick the app type
**installed app** — a *web app* or *script* id comes with a client secret and
Reddit then rejects the anonymous login this app uses (every scan fails
with 401). Takes effect immediately, no restart needed.

## ComfyUI shows as unreachable

Check **Settings → Local tools → ComfyUI API URL** (default
\`http://127.0.0.1:8188\`), confirm ComfyUI is actually running, and check that a
firewall or a different bind interface isn't blocking the connection. The
**Test** button answers immediately.

## Klein engine stays greyed out

Klein needs a reachable ComfyUI **and** the Klein model files (~16 GB VRAM
class). **Setup → ComfyUI** offers the download; the license-gated fp8 model
needs a Hugging Face token (Settings → Local tools).

## Port 5000 conflict on macOS

macOS reserves port 5000 for AirPlay Receiver. Change the port in
**Settings → Server & access** (e.g. 5050) and restart.

## Garbled characters in the Windows console

Cosmetic only — some UTF-8 text renders wrong on the legacy console codepage.
The app itself is unaffected.

## \`pnpm install\` fails with \`Cannot find module @rollup/rollup-<platform>-...\`

Only relevant if you rebuild the frontend yourself (the repo ships \`dist/\`
prebuilt). Delete \`frontend/node_modules\` and run \`pnpm install\` again on this
machine.

## A cloud run seems stuck

Open the **Cloud** tab: every run shows its live phase, and the stall watchdog
(Settings → Training → stall timeout) rescues logs and kills the pod if no step
progress happens for too long. Orphaned pods are also destroyed automatically
at every app start — you never pay for a forgotten GPU.
`,P=`# Getting help & reporting problems

Stuck, found a bug, or missing a feature? Two doors, both watched:

- **Discord** — [discord.gg/j6hnJBFtXE](https://discord.gg/j6hnJBFtXE) — ask in
  **#help**; usually the fastest way to get unstuck. Feature ideas and votes
  live in **#roadmap**.
- **GitHub** — [Issues](https://github.com/perfectgf/lora-dataset-studio/issues) —
  best for reproducible bugs and feature requests; the templates walk you
  through what to include.

---

## What makes a report solvable

The difference between a five-minute fix and a week of guessing is almost
always the same four things:

1. **Version** — shown in Settings → Maintenance → Updates ("Current build").
2. **Environment** — OS, and whether you run API-only, full local, or Docker.
3. **What you did → what you expected → what happened** — three short lines
   beat three paragraphs.
4. **The log** — the last lines of the server log usually name the real error.
   Settings → Maintenance → 🪵 Server log → **Copy all**.

## Or let the app write it for you

The **diagnostic report** button below assembles all of that in one click:
version, OS, capability status, non-secret settings and the last log lines —
formatted, copied to your clipboard, ready to paste into Discord or a GitHub
issue.

What it deliberately **never** includes: your API keys or tokens (only
whether each one is set) and your folder paths (only whether each one is
configured). One caveat: the log tail can mention file names from your machine
— skim the paste before posting if that matters to you.

## Feature requests

Describe the **job you were doing when you missed the feature** — the problem
is more valuable than the proposed solution. Post it in Discord **#roadmap** or
open a GitHub issue with the *Feature request* template.
`,b=[{id:"getting-started",num:"01",title:"Getting started",description:"Install the app, connect the tools you need, and understand the workspace.",source:L},{id:"using-the-app",num:"02",title:"Using the app",description:"Follow the complete workflow for character, concept, and style datasets.",source:A},{id:"dataset-guide",num:"03",title:"Building a good dataset",description:"Make stronger choices about images, captions, settings, and checkpoints.",source:R},{id:"troubleshooting",num:"04",title:"Troubleshooting",description:"Find a symptom, understand the cause, and apply the shortest reliable fix.",source:C}],F={id:"getting-help",num:"05",title:"Getting help",description:"Create a useful report and share the details needed to solve a problem.",source:P,extra:"diagnostic"},U=a=>a.replace(/[`*_]/g,"");function D({helpOnly:a=!1}){const{section:r}=k(),i=j(),t=a?[F]:b,s=a?0:Math.max(0,t.findIndex(l=>l.id===r)),o=t[s],d=s>0?t[s-1]:null,n=s<t.length-1?t[s+1]:null,c=[...o.source.matchAll(/^##\s+(.+)$/gm)].map(l=>({title:U(l[1]),id:x(l[1])})),h=Math.max(1,Math.ceil(o.source.trim().split(/\s+/).length/210)),u=l=>{var g;return(g=document.getElementById(l))==null?void 0:g.scrollIntoView({behavior:"smooth",block:"start"})};T.useEffect(()=>{window.scrollTo(0,0)},[o.id]);const m=(l,g)=>{const f=l.id===o.id,v=g?`flex shrink-0 items-baseline gap-1.5 whitespace-nowrap rounded-full border px-3 py-1.5 text-xs font-medium ${f?"border-border-strong bg-surface-raised text-content":"border-border text-content-muted hover:text-content"}`:`relative flex w-full items-baseline gap-2.5 rounded-md px-3 py-2 text-left text-sm ${f?"bg-surface-raised text-content":"text-content-muted hover:bg-surface hover:text-content"}`;return e.jsxs("button",{type:"button",onClick:()=>i(`/guide/${l.id}`),"aria-current":f?"page":void 0,className:v,children:[!g&&f&&e.jsx("span",{"aria-hidden":!0,className:"absolute bottom-1.5 left-0 top-1.5 w-0.5 rounded bg-gradient-primary"}),e.jsx("span",{className:`font-mono text-[11px] ${f?"text-content":"text-content-subtle"}`,children:l.num}),e.jsx("span",{className:"font-medium",children:l.title})]},l.id)};return e.jsxs("div",{className:a?"mx-auto max-w-5xl xl:grid xl:grid-cols-[minmax(0,1fr)_190px] xl:items-start xl:gap-7":"lg:grid lg:grid-cols-[210px_minmax(0,1fr)] lg:items-start lg:gap-7 xl:grid-cols-[210px_minmax(0,1fr)_190px]",children:[!a&&e.jsxs("aside",{children:[e.jsx("nav",{"aria-label":"Guide chapters",className:"-mx-4 flex gap-2 overflow-x-auto px-4 pb-3 lg:hidden",children:b.map(l=>m(l,!0))}),e.jsxs("nav",{"aria-label":"Guide chapters",className:"hidden lg:sticky lg:top-20 lg:block",children:[e.jsx("p",{className:"px-3 pb-2 font-mono text-[11px] uppercase tracking-[0.18em] text-content-subtle",children:"Field manual"}),e.jsx("div",{className:"flex flex-col gap-0.5",children:b.map(l=>m(l,!1))})]})]}),e.jsxs("main",{className:`min-w-0 max-w-4xl pb-10 ${a?"mx-auto":"mt-2 lg:mt-0"}`,children:[e.jsxs("header",{className:"relative mb-4 overflow-hidden rounded-2xl border border-border bg-surface px-5 py-5 sm:px-6 sm:py-6",children:[e.jsx("div",{"aria-hidden":!0,className:"absolute -right-16 -top-20 h-52 w-52 rounded-full bg-indigo-500/10 blur-3xl"}),e.jsxs("div",{className:"relative",children:[e.jsxs("div",{className:"mb-3 flex flex-wrap items-center gap-2 font-mono text-[0.6875rem] uppercase tracking-[0.14em] text-content-subtle",children:[e.jsx("span",{className:"rounded-md border border-indigo-400/30 bg-indigo-500/10 px-2 py-1 text-indigo-300",children:a?"Support":`Chapter ${o.num}`}),e.jsxs("span",{children:[h," min read"]}),!a&&e.jsxs(e.Fragment,{children:[e.jsx("span",{"aria-hidden":!0,children:"·"}),e.jsxs("span",{children:[s+1," of ",t.length]})]})]}),e.jsx("h1",{className:"m-0 max-w-2xl text-2xl font-bold tracking-tight text-content sm:text-3xl",children:o.title}),e.jsx("p",{className:"mb-0 mt-2 max-w-2xl text-sm leading-relaxed text-content-muted sm:text-base",children:o.description})]})]}),c.length>0&&e.jsxs("nav",{"aria-label":"On this page",className:"mb-4 rounded-xl border border-border bg-surface p-3 xl:hidden",children:[e.jsx("p",{className:"m-0 mb-2 font-mono text-[0.625rem] uppercase tracking-[0.16em] text-content-subtle",children:"On this page"}),e.jsx("div",{className:"flex gap-2 overflow-x-auto pb-0.5",children:c.map(l=>e.jsx("button",{type:"button",onClick:()=>u(l.id),className:"shrink-0 rounded-full border border-border bg-transparent px-2.5 py-1 text-xs text-content-muted hover:border-border-strong hover:text-content",children:l.title},l.id))})]}),e.jsx(I,{source:o.source,variant:"guide"}),o.extra==="diagnostic"&&e.jsx("div",{className:"mt-6",children:e.jsx(N,{})}),!a&&e.jsxs("div",{className:"mt-6 grid grid-cols-2 gap-3 border-t border-border pt-4",children:[d?e.jsxs(w,{to:`/guide/${d.id}`,className:"group flex min-w-0 items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2.5 no-underline hover:bg-surface-raised",children:[e.jsx("span",{"aria-hidden":!0,className:"text-content-subtle",children:"←"}),e.jsxs("span",{className:"min-w-0",children:[e.jsx("span",{className:"block font-mono text-[0.625rem] uppercase tracking-wider text-content-subtle",children:"Previous"}),e.jsx("span",{className:"block truncate text-sm font-medium text-content-muted group-hover:text-content",children:d.title})]})]}):e.jsx("span",{}),n?e.jsxs(w,{to:`/guide/${n.id}`,className:"group flex min-w-0 items-center justify-end gap-2 rounded-lg border border-border bg-surface px-3 py-2.5 text-right no-underline hover:bg-surface-raised",children:[e.jsxs("span",{className:"min-w-0",children:[e.jsx("span",{className:"block font-mono text-[0.625rem] uppercase tracking-wider text-content-subtle",children:"Next"}),e.jsx("span",{className:"block truncate text-sm font-medium text-content-muted group-hover:text-content",children:n.title})]}),e.jsx("span",{"aria-hidden":!0,className:"text-content-subtle",children:"→"})]}):e.jsx("span",{})]})]}),e.jsx("aside",{className:"hidden xl:block",children:e.jsxs("nav",{"aria-label":"On this page",className:"sticky top-20 border-l border-border pl-4",children:[e.jsx("p",{className:"m-0 mb-2 font-mono text-[0.625rem] uppercase tracking-[0.16em] text-content-subtle",children:"On this page"}),e.jsx("div",{className:"flex flex-col gap-0.5",children:c.map(l=>e.jsx("button",{type:"button",onClick:()=>u(l.id),className:"rounded-md bg-transparent px-2 py-1.5 text-left text-xs leading-snug text-content-subtle hover:bg-surface hover:text-content",children:l.title},l.id))})]})})]})}export{D as default};
