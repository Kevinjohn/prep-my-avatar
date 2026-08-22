import{j as e,t as j,r as T,N as S,L as k}from"./index-C4V-DnK8.js";import{D as N}from"./DiagnosticReport-oG8ky4c5.js";function C(o){return String(o||"").replace(/[`*_]/g,"").normalize("NFKC").toLocaleLowerCase().replace(/[^\p{Letter}\p{Number}]+/gu,"-").replace(/^-|-$/g,"")||"section"}function I(o){const s=new Map;return o.map(i=>{const t=C(i),n=(s.get(t)||0)+1;return s.set(t,n),n===1?t:`${t}-${n}`})}function P(o){const s=[...String(o||"").matchAll(/^##\s+(.+)$/gm)].map(t=>t[1]),i=I(s);return s.map((t,n)=>({title:t.replace(/[`*_]/g,""),id:i[n]}))}function f(o,s="i",i){const t=[],n=/(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)|(\[[^\]]+\]\([^)]+\))/g;let h=0,r,a=0;for(;(r=n.exec(o))!==null;){r.index>h&&t.push(o.slice(h,r.index));const l=r[0],p=`${s}-${a++}`;if(l.startsWith("`"))t.push(e.jsx("code",{className:"px-1 py-0.5 rounded bg-surface-raised text-indigo-200 text-[0.8125em] font-mono",children:l.slice(1,-1)},p));else if(l.startsWith("**"))t.push(e.jsx("strong",{className:"text-content font-semibold",children:l.slice(2,-2)},p));else if(l.startsWith("*"))t.push(e.jsx("em",{children:l.slice(1,-1)},p));else{const c=l.match(/^\[([^\]]+)\]\(([^)]+)\)$/),u=i==null?void 0:i(c[2]);t.push(u==null?e.jsx("a",{href:c[2],target:"_blank",rel:"noreferrer",className:"text-indigo-300 underline decoration-indigo-400/40 hover:decoration-indigo-300",children:c[1]},p):e.jsx("a",{href:u,className:"text-indigo-300 underline decoration-indigo-400/40 hover:decoration-indigo-300",children:c[1]},p))}h=r.index+l.length}return h<o.length&&t.push(o.slice(h)),t}function R(o){const s=o.replace(/\r\n/g,`
`).split(`
`),i=[];let t=0;for(;t<s.length;){const n=s[t];if(!n.trim()){t++;continue}if(n.startsWith("```")){const a=[];for(t++;t<s.length&&!s[t].startsWith("```");)a.push(s[t++]);t++,i.push({t:"code",body:a.join(`
`)});continue}const h=n.match(/^(#{1,3})\s+(.*)$/);if(h){i.push({t:`h${h[1].length}`,body:h[2]}),t++;continue}if(/^(-{3,}|\*{3,})\s*$/.test(n)){i.push({t:"hr"}),t++;continue}if(n.startsWith(">")){const a=[];for(;t<s.length&&s[t].startsWith(">");)a.push(s[t++].replace(/^>\s?/,""));i.push({t:"quote",body:a.join(" ")});continue}if(/^\|/.test(n)){const a=[];for(;t<s.length&&/^\|/.test(s[t]);)a.push(s[t++]);const l=m=>m.replace(/^\||\|$/g,"").split("|").map(b=>b.trim()),p=l(a[0]),c=a[1]?l(a[1]):[];c.length===p.length&&c.every(m=>/^:?-{3,}:?$/.test(m))?i.push({t:"table",header:p,body:a.slice(2).map(l)}):a.forEach(m=>i.push({t:"p",body:m}));continue}if(/^(\s*)([-*]|\d+\.)\s+/.test(n)){const a=[],l=/^\s*\d+\./.test(n);for(;t<s.length&&/^(\s*)([-*]|\d+\.)\s+/.test(s[t]);){let p=s[t].replace(/^(\s*)([-*]|\d+\.)\s+/,"");for(t++;t<s.length&&/^\s{2,}\S/.test(s[t])&&!/^(\s*)([-*]|\d+\.)\s+/.test(s[t]);)p+=" "+s[t++].trim();a.push(p)}i.push({t:"list",ordered:l,items:a});continue}const r=[n];for(t++;t<s.length&&s[t].trim()&&!/^(#{1,3}\s|```|\||>|(\s*)([-*]|\d+\.)\s|-{3,}\s*$)/.test(s[t]);)r.push(s[t++]);i.push({t:"p",body:r.join(" ")})}return i}function w(o,s,i=!1,t){const n=`b${s}`;switch(o.t){case"h1":return e.jsx("h1",{className:"m-0 mt-2 text-content font-bold text-2xl",children:f(o.body,n,t)},n);case"h2":return e.jsx("h2",{id:i?void 0:o.headingId,className:`${i?"text-xl":"mt-4 border-b border-border pb-1.5 text-lg"} m-0 scroll-mt-24 text-content font-bold`,children:f(o.body,n,t)},n);case"h3":return e.jsx("h3",{className:"m-0 mt-2 text-content font-semibold text-base",children:f(o.body,n,t)},n);case"hr":return e.jsx("hr",{className:"border-border my-2"},n);case"quote":return e.jsx("blockquote",{className:"m-0 rounded-lg border border-indigo-400/40 bg-indigo-500/10 px-4 py-3 text-content text-sm leading-relaxed",children:f(o.body,n,t)},n);case"code":return e.jsx("pre",{tabIndex:0,className:"m-0 rounded-lg border border-border bg-app/60 p-3 overflow-x-auto text-[0.8125rem] text-content-muted font-mono",children:o.body},n);case"table":return e.jsx("div",{tabIndex:0,className:"overflow-x-auto rounded-lg border border-border",children:e.jsxs("table",{className:"w-full text-sm border-collapse",children:[e.jsx("thead",{children:e.jsx("tr",{className:"bg-surface-raised",children:o.header.map((h,r)=>e.jsx("th",{className:"text-left px-3 py-2 text-content font-semibold border-b border-border whitespace-nowrap",children:f(h,`${n}h${r}`,t)},r))})}),e.jsx("tbody",{children:o.body.map((h,r)=>e.jsx("tr",{className:r%2?"bg-surface":"",children:h.map((a,l)=>e.jsx("td",{className:"px-3 py-2 text-content-muted align-top border-b border-border last:border-b-0",children:f(a,`${n}r${r}c${l}`,t)},l))},r))})]})},n);case"list":{const h=o.ordered?"ol":"ul";return e.jsx(h,{className:`m-0 flex flex-col text-sm text-content-muted ${i&&o.ordered?"list-none gap-2 p-0":`gap-1.5 pl-5 ${o.ordered?"list-decimal":"list-disc"}`}`,children:o.items.map((r,a)=>{const l=r.match(/^\[([ xX])\]\s+(.*)$/);return l?e.jsxs("li",{className:"list-none -ml-5 flex items-start gap-2",children:[e.jsx("span",{"aria-hidden":!0,className:`mt-0.5 grid place-items-center w-4 h-4 shrink-0 rounded border text-[0.625rem] ${l[1]===" "?"border-border-strong text-transparent":"border-emerald-400/60 bg-emerald-500/15 text-emerald-300"}`,children:"✓"}),e.jsx("span",{children:f(l[2],`${n}i${a}`,t)})]},a):i&&o.ordered?e.jsxs("li",{className:"flex gap-3 rounded-lg border border-border bg-app px-3 py-3 leading-relaxed",children:[e.jsx("span",{"aria-hidden":!0,className:"grid h-6 w-6 shrink-0 place-items-center rounded-md bg-indigo-500/15 font-mono text-[0.6875rem] font-bold text-indigo-300",children:String(a+1).padStart(2,"0")}),e.jsx("span",{children:f(r,`${n}i${a}`,t)})]},a):e.jsx("li",{children:f(r,`${n}i${a}`,t)},a)})},n)}default:return e.jsx("p",{className:"m-0 text-sm text-content-muted leading-relaxed",children:f(o.body,n,t)},n)}}function U({source:o,variant:s="default",resolveLink:i}){const t=R(o||""),n=t.filter(r=>r.t==="h2"),h=I(n.map(r=>r.body));if(n.forEach((r,a)=>{r.headingId=h[a]}),s==="guide"){const r=t.filter((c,u)=>!(u===0&&c.t==="h1")),a=[],l=[];let p=null;return r.forEach((c,u)=>{c.t==="h2"?(p={heading:c,blocks:[],index:u},l.push(p)):p?p.blocks.push({block:c,index:u}):c.t!=="hr"&&a.push({block:c,index:u})}),e.jsxs("div",{className:"flex max-w-none flex-col gap-4",children:[a.length>0&&e.jsx("div",{className:"flex flex-col gap-3 rounded-xl border border-indigo-400/20 bg-gradient-to-br from-indigo-500/10 via-surface to-surface px-4 py-4 sm:px-5",children:a.map(({block:c,index:u})=>w(c,u,!0,i))}),l.map(({heading:c,blocks:u,index:m})=>e.jsxs("section",{id:c.headingId,className:"scroll-mt-24 rounded-xl border border-border bg-surface px-4 py-4 shadow-sm shadow-black/10 sm:px-5 sm:py-5",children:[e.jsxs("div",{className:"mb-4 flex items-start gap-3 border-b border-border pb-3",children:[e.jsx("span",{"aria-hidden":!0,className:"mt-1 h-5 w-1 shrink-0 rounded-full bg-gradient-primary"}),w(c,m,!0,i)]}),e.jsx("div",{className:"flex flex-col gap-3",children:u.map(({block:b,index:d})=>w(b,d,!0,i))})]},c.headingId))]})}return e.jsx("div",{className:"flex max-w-none flex-col gap-3",children:t.map((r,a)=>w(r,a,!1,i))})}const L=`# Getting started

> Prefer a visual walkthrough? Launch the app and choose **Guide → Getting started**, or open \`docs/guide/getting-started.html\` from your local copy of the repository. This Markdown file is the plain-text reference.

## The problem this solves

You need recognisable photos or videos of yourself repeatedly—for a website, social post, presentation, campaign, thumbnail, or story. Another photoshoot every time is slow, and starting from scratch with an image tool can produce a different-looking person on every attempt. The goal is not to own an avatar. The goal is to make useful new material featuring your likeness without rebuilding that likeness for every image, video, or service.

This is useful for creators, founders, educators, performers, campaigners, and anyone else who regularly needs consistent images of themselves.

The problem is repetition and inconsistency: useful photographs are scattered, similar selfies provide limited evidence, and each image tool can create a different-looking person. Prep My Avatar helps you prepare reliable evidence once. Start with five strong photos, review them, and add genuinely different views only when your intended result needs them. You can then use those photos directly with a capable model or train a compatible LoRA when you need repeated consistency and more control.

“Digital avatar” is only shorthand for several possible solutions. Prep My Avatar can prepare reference images, export a portable image-and-caption training pack, or train a family-specific Character LoRA. A provider-owned avatar—such as Gemini’s face-and-voice personal avatar—is created and stored by that provider, not by this app.

Choose where you want to reuse your likeness before choosing tools:

| You want | The actual output | Where it goes |
| --- | --- | --- |
| New still images of yourself | Reference photos and finished image files | A service that accepts image references, including the supported in-app generation engines |
| A reusable image-model identity | A Character LoRA \`.safetensors\` file tied to one model family | A compatible Z-Image, SDXL, Krea 2, FLUX.1, or FLUX.2 Klein workflow |
| A Gemini personal avatar | A face-and-voice avatar linked to your Google account | Gemini and Google products where available; create this directly with Google |
| Training material for another tool | A ZIP of PNG/TXT pairs plus a provenance manifest | ai-toolkit, kohya_ss / sd-scripts, OneTrainer, and similar trainers |

You can start by importing five photos and reviewing them without an API key, a local GPU, or a training account. A final LoRA requires more accepted images and a compatible local or cloud training route.

---

## What you need before you open the app

### Images of the person or subject

For a character dataset, start with photos you own or have permission to process. Five clear photos are enough to test the workflow, but they are not an ideal final training set. More useful variety gives the app more to work with: different framings, angles, expressions, lighting, poses, backgrounds, and clothing.

There is no hard five-photo minimum. The app's coverage plan will show which kinds of images are covered and which are still missing. You can add more photos later.

Keep the original files somewhere safe. The app preserves imported originals and creates its own training derivatives.

### A clear goal

When you create a dataset, choose the kind that matches what you want to teach:

| Choose | Use it for | What you provide |
| --- | --- | --- |
| **Character** | A person or face | A name, a unique trigger word, and photos of the person |
| **Concept** | A recurring action, effect, object, or idea | A name, a unique trigger word, a description of what the captions must leave out, and example images |
| **Style** | A visual aesthetic applied across images | A name and varied images that share the style; no prompt trigger is required |

For a first run with photos of yourself, choose **Character**. Use a distinctive trigger such as \`zchar_alex\`, not a common word such as \`alex\` or \`person\`.

You will also choose a target model family. This controls the caption format and can be changed later. The default **Z-Image** option uses prose captions.

### Decide how far you want to go

| Your goal | You need now | You can skip for now |
| --- | --- | --- |
| Try the workflow with your own photos | The app and five or more test photos | API keys, ComfyUI, Ollama, and a GPU |
| Generate missing poses or framings | A Gemini API key, an OpenAI API key, or local Klein through ComfyUI | ai-toolkit and cloud training |
| Get automatic captions and coverage mapping | Ollama plus the configured vision model | ComfyUI and ai-toolkit |
| Train on your own machine | ai-toolkit and its compatible local environment | A generation API key |
| Train without a local GPU | A vast.ai API key and account credit | Local ai-toolkit and a local GPU |
| Prepare data for another trainer | The app and your source images | All generation and training tools |

The safest first step is to import your photos, review them, and export a small test dataset. Add generation or training tools when you know you need them.

---

## Install and launch

See the repository's canonical [Installation and launch](https://github.com/Kevinjohn/prep-my-avatar#installation-and-launch) section for the supported installation routes.

### Windows: use the bundled launcher

Clone or download the repository, then double-click **\`start.bat\`**. It creates the local Python environment, installs the core dependencies, starts the app, and opens it at:

\`\`\`text
http://127.0.0.1:5050/
\`\`\`

The launcher prefers Python 3.11 or 3.12. If neither is installed, it can download a self-contained Python 3.12 on an online Windows machine. The app's core features can run without the optional machine-learning extras.

### macOS or Linux: run the launcher manually

Use Python 3.11 or 3.12 if you want the optional face scoring, person masks, or watermark tools. The core application requires Python 3.10 or newer.

\`\`\`bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
python backend/source_launcher.py --install --root . --data-dir data
python data/source-launcher.py --root . --data-dir data
\`\`\`

Then open \`http://127.0.0.1:5050/\` in your browser.

On Windows, the equivalent manual commands use \`.venv\\Scripts\\activate\` and \`python\` rather than \`python3\`.

### Docker: API-only mode

Docker runs the core app and does not include ComfyUI or ai-toolkit. Create a \`.env\` file next to \`docker-compose.yml\`, add a long random access token, and start the container:

Put this in \`.env\`:

\`\`\`dotenv
LDS_ACCESS_TOKEN=replace-with-a-long-random-value
\`\`\`

Then run:

\`\`\`bash
docker compose up --build
\`\`\`

Open \`http://127.0.0.1:5050/remote-login\` and enter the token from \`.env\`.

---

## Complete the Setup wizard

The first time you open the app, it takes you to **Setup**. Let it scan your machine, then configure only the steps you need. You can skip a step and return to it later from **Setup** or **Settings**.

### Image generation

Add one of these keys if you want the app to generate images for missing coverage:

- **Gemini API key** — enables Nano Banana. Get one from [Google AI Studio](https://aistudio.google.com/apikey).
- **OpenAI API key** — enables ChatGPT image generation. Get one from [OpenAI API keys](https://platform.openai.com/api-keys).

You do not need both. Save and test the key in the wizard. The key is stored locally in the app's environment file and is not shown again.

If you use a remote engine, go to **Settings → Image engines → Remote-generation privacy** and enable remote generation before making a request. The app sends the prompt and the bounded reference pack to the provider you select. Images marked **Exclude** stay out of that pack.

### ComfyUI and local Klein

Install ComfyUI separately if you want local image generation or **Test Studio**. Point **Setup → ComfyUI** at:

- the ComfyUI API, normally \`http://127.0.0.1:8188\`; and
- the ComfyUI folder containing \`main.py\` and \`models/\`.

Local Klein is optional. It needs the Klein model files and a machine with roughly 16 GB of VRAM for the fp8 model. The Setup step can download the supported files after the ComfyUI folder has been validated.

### Ollama and automatic analysis

Install and start [Ollama](https://ollama.com/download), then use the Setup step to pull the configured vision model. Ollama enables automatic captions, coverage classification, and head-crop assistance. Ollama being installed is not enough—the vision model must also be available.

If you do not want to install Ollama yet, you can still import, review, manually caption, and export. The automatic coverage and captioning steps will not be available until a vision model is ready.

### Quality tools

The **Quality tools** step installs optional local helpers for face-similarity scoring, person masks, and watermark inpainting. They improve review and cleanup but do not replace your judgment, and the app can work without them.

Use Python 3.11 or 3.12 for the reviewed machine-learning dependency set. On another Python version, skip these tools or configure a separate supported interpreter in **Settings → Local tools**.

### Training

Choose one training route only when you are ready:

- **Local training:** install [ai-toolkit](https://github.com/ostris/ai-toolkit) and point **Setup → ai-toolkit** at its folder.
- **Cloud training:** add a vast.ai API key in **Settings → Training**. Cloud runs use rented GPUs and cost money; review the price and budget limits before launching.
- **Training elsewhere:** skip this step and use **Export ZIP** after curation and captioning.

---

## The first dataset workflow

Follow this order for a character dataset. The workspace keeps the next useful step visible as you go.

1. **Create a Character dataset.** Open **Datasets → New dataset**, enter a name, choose a unique trigger word, select a target model, and choose **Face** or **Face + body** fidelity. Start with **Face** unless you specifically need the LoRA to reproduce body shape or permanent body marks.

   You should now see an empty dataset workspace with an import area.

2. **Import your source photos.** Add your five test photos or your larger collection. The app keeps the originals, skips exact reimports, and keeps near-duplicates visible so you can decide what to do with them.

   Start with the real corpus. This lets the coverage plan identify genuine gaps before you spend money on generation.

3. **Review and admit useful images.** Run the local technical analysis if available. Review sharpness, exposure, duplicates, framing, rights, and identity. Mark the images you want to train on as **Keep**. Reject or leave out images that are blurry, repeated, unsuitable, or not yours to use.

4. **Map coverage.** With Ollama available, classify the imported photos and open the coverage plan. It distinguishes covered, weak, missing, and unknown framing or visual combinations. Unknown evidence means “review this,” not “generate a replacement.”

5. **Choose a reference and anchors.** Set a primary reference if you want local Klein or want to pin a particular identity image. Otherwise, the app can select a bounded and diverse anchor pack from the imported corpus for API generation. Keep provider-sensitive images marked **Exclude**.

6. **Generate only real gaps.** If the coverage plan recommends missing shots and you configured an engine, select the suggested shots and generate them. Each result keeps its engine, prompt, target gap, and reference provenance.

   If you do not have an API key or ComfyUI, skip this step. You can still train or export the photos you kept.

7. **Curate the combined set.** Review imported and generated images together. Keep the images that are useful and on-identity. Use face-similarity scores as a ranking aid when the quality tool is installed. For a low-quality source, use **Reconstruct & compare** and keep either the original or the reconstruction, never both.

8. **Caption the kept images.** Run captioning, then read the results. For a character dataset, captions should describe the pose, clothes, setting, lighting, and framing without turning the person's identity into prompt text. Fix every identity-leak warning before training.

9. **Train or export.** Run the training preflight. It checks counts, balance, captions, duplicates, quality, identity, watermarks, provenance, rights, and the source mix. Then either choose **Train locally**, choose **Train in cloud**, or choose **Export ZIP** for another trainer.

10. **Evaluate and protect the result.** If ComfyUI is configured, use **Test Studio** to compare checkpoints with fixed seeds and save the strongest settings. Create a **Backup** from the dataset workspace before making a large change or moving to another machine.

---

## Before your first generation or training run

Check these items:

- You have permission to use every identifiable person's image.
- Your trigger word is unique and consistent.
- You know whether you are training face-only or face-plus-body fidelity.
- The imported set contains real variety, not five near-identical crops.
- Remote generation is enabled only if you understand what will leave your machine.
- Every generated image you keep has a reason to be in the dataset.
- Captions do not describe the character's identity or permanent features as ordinary prompt words.
- You know whether the next step is local training, paid cloud training, or export.
- You have a portable backup before deleting or moving the dataset.

---

## What to read next

- **[Using the app](using-the-app.md)** — the detailed walkthrough for character, concept, and style datasets.
- **[Building a good dataset](../DATASET_GUIDE.md)** — why variety, captions, coverage, and identity checks matter.
- **[Troubleshooting](troubleshooting.md)** — fixes for the most common setup and training problems.
`,F=`# Using the app

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
`,G=`# Building a good LoRA dataset

This guide condenses what actually moves the needle when training a character LoRA
with this app (ai-toolkit under the hood). Every number here matches what the app
enforces or defaults to — when in doubt, the app's warnings are this guide applied.

> **The one principle behind everything:** a LoRA learns whatever is **constant
> across your images and NOT described in the captions**. Keep the subject constant,
> vary everything else, and never describe the subject — that's the trigger word's job.

## Evidence status of operational guidance

Hardware ranges, download sizes, run-time descriptions, and checkpoint regions
in this guide are planning heuristics, not benchmark guarantees. They have not
been reproduced across a controlled hardware matrix in this repository. Treat
them as starting points and record the actual peak memory, duration, dependency
versions, GPU and dataset shape for your run before making a purchasing or
capacity decision.

The behavior the application actually enforces is reviewable in these sources:

- training defaults and checkpoint cadence: \`backend/app/services/lora_training.py\`;
- family/model choices and validation: \`backend/app/routes/training.py\` and
  \`backend/app/services/cloud_training.py\`;
- GPU speed estimates: \`backend/app/services/gpu_speed.py\`;
- frontend preset presentation: \`frontend/src/components/dataset/TrainingPanel.jsx\`.

When an estimate changes, update this guide with the measurement date, GPU,
driver/tool versions, model revision, dataset image count and resolution, peak
memory method, elapsed time, and checkpoint scoring method. Until such a result
is committed, wording here deliberately remains approximate.

---

## 1. Pick your model family first

The family changes the caption style, the image count, and the settings — so decide
before you caption anything.

| Setting | Z-Image | SDXL | Krea 2 | FLUX.1 | FLUX.2 Klein |
|---|---|---|---|---|---|
| **Caption style** | Prose sentences | Booru tags | Prose sentences | Prose sentences | Prose sentences |
| **Images (min → good)** | 12 → 20+ | 20 → 30+ | 15 → 20+ | 15 → 20+ | 15 → 20+ |
| **Training base** | Z-Image-Turbo (or a converted custom merge) | Your ComfyUI checkpoint (e.g. bigLove) | Krea-2-Raw (default) or Turbo | FLUX.1-dev (gated HF) | FLUX.2-klein-base 4B (default) or 9B (gated HF) |
| **Preview quality** | Fast, distilled | Depends on checkpoint | Raw: slow but faithful | High, ~20 steps | Non-distilled, real CFG (~25 steps) |
| **Best for** | Fast iteration, prose-driven prompting | Booru-native checkpoints, NSFW ecosystems | Highest realism ceiling | The largest LoRA ecosystem, strong prompt fidelity | Modern FLUX.2 stack; 4B trains on mid-range GPUs |

**Krea note:** the project default trains on **Krea-2-Raw** and uses the working
strategy *train on Raw, validate on Turbo*. Raw runs can take hours; use live
step progress and the configured stall timeout rather than elapsed time alone
to decide whether a run is stuck.

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
`,K=`# Troubleshooting

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
progress happens for too long. At startup the app also retries cleanup of cloud
runs it still knows about, but local cleanup success is not a billing guarantee:
provider requests can fail and a run created outside this app is not tracked.
Until the provider console confirms the instance is terminated, assume it may
still be billable and terminate it there manually if necessary.
`,O=`# Getting help & reporting problems

Stuck, found a bug, or missing a feature?

- **GitHub** — [Prep My Avatar issues](https://github.com/Kevinjohn/prep-my-avatar/issues)
  is the supported destination for reproducible bugs and feature requests; the
  templates walk you through what to include.
- **Upstream community** — the inherited application's
  [Discord](https://discord.gg/j6hnJBFtXE) may help with LoRA Dataset Studio
  behavior, but it does not own or support this fork's changes.

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
issue in this repository.

What it deliberately **never** includes: your API keys or tokens (only
whether each one is set) and your folder paths (only whether each one is
configured). One caveat: the log tail can mention file names from your machine
— skim the paste before posting if that matters to you.

## Feature requests

Describe the **job you were doing when you missed the feature** — the problem
is more valuable than the proposed solution. Open a GitHub issue with the
*Feature request* template.
`,v=[{id:"getting-started",num:"01",title:"Getting started",description:"Prepare a reusable likeness so you can create recognisable photos and videos of yourself without starting over each time.",source:L},{id:"using-the-app",num:"02",title:"Using the app",description:"Follow the complete workflow for character, concept, and style datasets.",source:F},{id:"dataset-guide",num:"03",title:"Building a good dataset",description:"Make stronger choices about images, captions, settings, and checkpoints.",source:G},{id:"troubleshooting",num:"04",title:"Troubleshooting",description:"Find a symptom, understand the cause, and apply the shortest reliable fix.",source:K}],A={id:"getting-help",num:"05",title:"Getting help",description:"Create a useful report and share the details needed to solve a problem.",source:O,extra:"diagnostic"},$=[...v,A],D=Object.freeze({"getting-started.md":"/guide/getting-started","using-the-app.md":"/guide/using-the-app","../DATASET_GUIDE.md":"/guide/dataset-guide","troubleshooting.md":"/guide/troubleshooting","getting-help.md":"/help"}),B=o=>{const s=D[o];return s?`#${s}`:null};function q({helpOnly:o=!1}){const{section:s}=j(),i=o?[A]:v,t=s||"getting-started",n=o?0:i.findIndex(d=>d.id===t),h=o||n>=0,r=T.useRef(null),a=h?i[n]:i[0],l=n>0?i[n-1]:null,p=n<i.length-1?i[n+1]:null,c=P(a.source),u=Math.max(1,Math.ceil(a.source.trim().split(/\s+/).length/210)),m=(d,y)=>{d.preventDefault();const g=document.getElementById(y);if(!g)return;window.history.pushState(null,"",`#${encodeURIComponent(y)}`),g.tabIndex=-1,g.focus({preventScroll:!0});const x=window.matchMedia("(prefers-reduced-motion: reduce)").matches;g.scrollIntoView({behavior:x?"auto":"smooth",block:"start"})};if(T.useEffect(()=>{var d;window.scrollTo(0,0),h&&((d=r.current)==null||d.focus())},[a.id,h]),!h)return e.jsx(S,{to:"/guide/getting-started",replace:!0});const b=(d,y)=>{const g=d.id===a.id,x=y?`flex shrink-0 items-baseline gap-1.5 whitespace-nowrap rounded-full border px-3 py-1.5 text-xs font-medium ${g?"border-border-strong bg-surface-raised text-content":"border-border text-content-muted hover:text-content"}`:`relative flex w-full items-baseline gap-2.5 rounded-md px-3 py-2 text-left text-sm ${g?"bg-surface-raised text-content":"text-content-muted hover:bg-surface hover:text-content"}`;return e.jsxs(k,{to:`/guide/${d.id}`,"aria-current":g?"page":void 0,className:x,children:[!y&&g&&e.jsx("span",{"aria-hidden":!0,className:"absolute bottom-1.5 left-0 top-1.5 w-0.5 rounded bg-gradient-primary"}),e.jsx("span",{className:`font-mono text-[11px] ${g?"text-content":"text-content-subtle"}`,children:d.num}),e.jsx("span",{className:"font-medium",children:d.title})]},d.id)};return e.jsxs("div",{className:o?"mx-auto max-w-5xl xl:grid xl:grid-cols-[minmax(0,1fr)_190px] xl:items-start xl:gap-7":"lg:grid lg:grid-cols-[210px_minmax(0,1fr)] lg:items-start lg:gap-7 xl:grid-cols-[210px_minmax(0,1fr)_190px]",children:[!o&&e.jsxs("aside",{children:[e.jsx("nav",{tabIndex:0,"aria-label":"Guide chapters",className:"-mx-4 flex gap-2 overflow-x-auto px-4 pb-3 lg:hidden",children:v.map(d=>b(d,!0))}),e.jsxs("nav",{"aria-label":"Guide chapters",className:"hidden lg:sticky lg:top-20 lg:block",children:[e.jsx("p",{className:"px-3 pb-2 font-mono text-[11px] uppercase tracking-[0.18em] text-content-subtle",children:"Field manual"}),e.jsx("div",{className:"flex flex-col gap-0.5",children:v.map(d=>b(d,!1))})]})]}),e.jsxs("section",{className:`min-w-0 max-w-4xl pb-10 ${o?"mx-auto":"mt-2 lg:mt-0"}`,children:[e.jsxs("header",{className:"relative mb-4 overflow-hidden rounded-2xl border border-border bg-surface px-5 py-5 sm:px-6 sm:py-6",children:[e.jsx("div",{"aria-hidden":!0,className:"absolute -right-16 -top-20 h-52 w-52 rounded-full bg-indigo-500/10 blur-3xl"}),e.jsxs("div",{className:"relative",children:[e.jsxs("div",{className:"mb-3 flex flex-wrap items-center gap-2 font-mono text-[0.6875rem] uppercase tracking-[0.14em] text-content-subtle",children:[e.jsx("span",{className:"rounded-md border border-indigo-400/30 bg-indigo-500/10 px-2 py-1 text-indigo-300",children:o?"Support":`Chapter ${a.num}`}),e.jsxs("span",{children:[u," min read"]}),!o&&e.jsxs(e.Fragment,{children:[e.jsx("span",{"aria-hidden":!0,children:"·"}),e.jsxs("span",{children:[n+1," of ",i.length]})]})]}),e.jsx("h1",{ref:r,tabIndex:-1,className:"m-0 max-w-2xl text-2xl font-bold tracking-tight text-content focus:outline-none sm:text-3xl",children:a.title}),e.jsx("p",{className:"mb-0 mt-2 max-w-2xl text-sm leading-relaxed text-content-muted sm:text-base",children:a.description})]})]}),c.length>0&&e.jsxs("nav",{"aria-label":"On this page",className:"mb-4 rounded-xl border border-border bg-surface p-3 xl:hidden",children:[e.jsx("p",{className:"m-0 mb-2 font-mono text-[0.625rem] uppercase tracking-[0.16em] text-content-subtle",children:"On this page"}),e.jsx("div",{tabIndex:0,className:"flex gap-2 overflow-x-auto pb-0.5",children:c.map(d=>e.jsx("a",{href:`#${d.id}`,onClick:y=>m(y,d.id),className:"shrink-0 rounded-full border border-border bg-transparent px-2.5 py-1 text-xs text-content-muted hover:border-border-strong hover:text-content",children:d.title},d.id))})]}),e.jsx(U,{source:a.source,variant:"guide",resolveLink:B}),a.extra==="diagnostic"&&e.jsx("div",{className:"mt-6",children:e.jsx(N,{})}),!o&&e.jsxs("div",{className:"mt-6 grid grid-cols-2 gap-3 border-t border-border pt-4",children:[l?e.jsxs(k,{to:`/guide/${l.id}`,className:"group flex min-w-0 items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2.5 no-underline hover:bg-surface-raised",children:[e.jsx("span",{"aria-hidden":!0,className:"text-content-subtle",children:"←"}),e.jsxs("span",{className:"min-w-0",children:[e.jsx("span",{className:"block font-mono text-[0.625rem] uppercase tracking-wider text-content-subtle",children:"Previous"}),e.jsx("span",{className:"block truncate text-sm font-medium text-content-muted group-hover:text-content",children:l.title})]})]}):e.jsx("span",{}),p?e.jsxs(k,{to:`/guide/${p.id}`,className:"group flex min-w-0 items-center justify-end gap-2 rounded-lg border border-border bg-surface px-3 py-2.5 text-right no-underline hover:bg-surface-raised",children:[e.jsxs("span",{className:"min-w-0",children:[e.jsx("span",{className:"block font-mono text-[0.625rem] uppercase tracking-wider text-content-subtle",children:"Next"}),e.jsx("span",{className:"block truncate text-sm font-medium text-content-muted group-hover:text-content",children:p.title})]}),e.jsx("span",{"aria-hidden":!0,className:"text-content-subtle",children:"→"})]}):e.jsx("span",{})]})]}),e.jsx("aside",{className:"hidden xl:block",children:e.jsxs("nav",{"aria-label":"On this page",className:"sticky top-20 border-l border-border pl-4",children:[e.jsx("p",{className:"m-0 mb-2 font-mono text-[0.625rem] uppercase tracking-[0.16em] text-content-subtle",children:"On this page"}),e.jsx("div",{className:"flex flex-col gap-0.5",children:c.map(d=>e.jsx("a",{href:`#${d.id}`,onClick:y=>m(y,d.id),className:"rounded-md bg-transparent px-2 py-1.5 text-left text-xs leading-snug text-content-subtle hover:bg-surface hover:text-content",children:d.title},d.id))})]})})]})}export{$ as ALL_GUIDE_CHAPTERS,v as CHAPTERS,D as GUIDE_DOCUMENT_ROUTES,A as HELP_CHAPTER,q as default,B as resolveGuideLink};
