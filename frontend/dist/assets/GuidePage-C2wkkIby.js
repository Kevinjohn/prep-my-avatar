import{j as e,t as O,n as D,E as B,r as v,N as E,L as I}from"./index-BjxMq0Up.js";import{D as G}from"./DiagnosticReport-D1VOLeSq.js";function K(n){return String(n||"").replace(/[`*_]/g,"").normalize("NFKC").toLocaleLowerCase().replace(/[^\p{Letter}\p{Number}]+/gu,"-").replace(/^-|-$/g,"")||"section"}function U(n){const o=new Map;return n.map(i=>{const t=K(i),a=(o.get(t)||0)+1;return o.set(t,a),a===1?t:`${t}-${a}`})}function M(n){const o=[...String(n||"").matchAll(/^##\s+(.+)$/gm)].map(t=>t[1]),i=U(o);return o.map((t,a)=>({title:t.replace(/[`*_]/g,""),id:i[a]}))}function y(n,o="i",i){const t=[],a=/(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)|(\[[^\]]+\]\([^)]+\))/g;let u=0,r,s=0;for(;(r=a.exec(n))!==null;){r.index>u&&t.push(n.slice(u,r.index));const d=r[0],m=`${o}-${s++}`;if(d.startsWith("`"))t.push(e.jsx("code",{className:"px-1 py-0.5 rounded bg-surface-raised text-indigo-200 text-[0.8125em] font-mono",children:d.slice(1,-1)},m));else if(d.startsWith("**"))t.push(e.jsx("strong",{className:"text-content font-semibold",children:d.slice(2,-2)},m));else if(d.startsWith("*"))t.push(e.jsx("em",{children:d.slice(1,-1)},m));else{const h=d.match(/^\[([^\]]+)\]\(([^)]+)\)$/),l=i==null?void 0:i(h[2]);t.push(l==null?e.jsx("a",{href:h[2],target:"_blank",rel:"noreferrer",className:"text-indigo-300 underline decoration-indigo-400/40 hover:decoration-indigo-300",children:h[1]},m):e.jsx("a",{href:l,className:"text-indigo-300 underline decoration-indigo-400/40 hover:decoration-indigo-300",children:h[1]},m))}u=r.index+d.length}return u<n.length&&t.push(n.slice(u)),t}function W(n){const o=n.replace(/\r\n/g,`
`).split(`
`),i=[];let t=0;for(;t<o.length;){const a=o[t];if(!a.trim()){t++;continue}if(a.startsWith("```")){const s=[];for(t++;t<o.length&&!o[t].startsWith("```");)s.push(o[t++]);t++,i.push({t:"code",body:s.join(`
`)});continue}const u=a.match(/^(#{1,3})\s+(.*)$/);if(u){i.push({t:`h${u[1].length}`,body:u[2]}),t++;continue}if(/^(-{3,}|\*{3,})\s*$/.test(a)){i.push({t:"hr"}),t++;continue}if(a.startsWith(">")){const s=[];for(;t<o.length&&o[t].startsWith(">");)s.push(o[t++].replace(/^>\s?/,""));i.push({t:"quote",body:s.join(" ")});continue}if(/^\|/.test(a)){const s=[];for(;t<o.length&&/^\|/.test(o[t]);)s.push(o[t++]);const d=f=>f.replace(/^\||\|$/g,"").split("|").map(b=>b.trim()),m=d(s[0]),h=s[1]?d(s[1]):[];h.length===m.length&&h.every(f=>/^:?-{3,}:?$/.test(f))?i.push({t:"table",header:m,body:s.slice(2).map(d)}):s.forEach(f=>i.push({t:"p",body:f}));continue}if(/^(\s*)([-*]|\d+\.)\s+/.test(a)){const s=[],d=/^\s*\d+\./.test(a);for(;t<o.length&&/^(\s*)([-*]|\d+\.)\s+/.test(o[t]);){let m=o[t].replace(/^(\s*)([-*]|\d+\.)\s+/,"");for(t++;t<o.length&&/^\s{2,}\S/.test(o[t])&&!/^(\s*)([-*]|\d+\.)\s+/.test(o[t]);)m+=" "+o[t++].trim();s.push(m)}i.push({t:"list",ordered:d,items:s});continue}const r=[a];for(t++;t<o.length&&o[t].trim()&&!/^(#{1,3}\s|```|\||>|(\s*)([-*]|\d+\.)\s|-{3,}\s*$)/.test(o[t]);)r.push(o[t++]);i.push({t:"p",body:r.join(" ")})}return i}function k(n,o,i=!1,t){const a=`b${o}`;switch(n.t){case"h1":return e.jsx("h1",{className:"m-0 mt-2 text-content font-bold text-2xl",children:y(n.body,a,t)},a);case"h2":return e.jsx("h2",{id:i?void 0:n.headingId,className:`${i?"text-xl":"mt-4 border-b border-border pb-1.5 text-lg"} m-0 scroll-mt-24 text-content font-bold`,children:y(n.body,a,t)},a);case"h3":return e.jsx("h3",{className:"m-0 mt-2 text-content font-semibold text-base",children:y(n.body,a,t)},a);case"hr":return e.jsx("hr",{className:"border-border my-2"},a);case"quote":return e.jsx("blockquote",{className:"m-0 rounded-lg border border-indigo-400/40 bg-indigo-500/10 px-4 py-3 text-content text-sm leading-relaxed",children:y(n.body,a,t)},a);case"code":return e.jsx("pre",{tabIndex:0,className:"m-0 rounded-lg border border-border bg-app/60 p-3 overflow-x-auto text-[0.8125rem] text-content-muted font-mono",children:n.body},a);case"table":return e.jsx("div",{tabIndex:0,className:"overflow-x-auto rounded-lg border border-border",children:e.jsxs("table",{className:"w-full text-sm border-collapse",children:[e.jsx("thead",{children:e.jsx("tr",{className:"bg-surface-raised",children:n.header.map((u,r)=>e.jsx("th",{className:"text-left px-3 py-2 text-content font-semibold border-b border-border whitespace-nowrap",children:y(u,`${a}h${r}`,t)},r))})}),e.jsx("tbody",{children:n.body.map((u,r)=>e.jsx("tr",{className:r%2?"bg-surface":"",children:u.map((s,d)=>e.jsx("td",{className:"px-3 py-2 text-content-muted align-top border-b border-border last:border-b-0",children:y(s,`${a}r${r}c${d}`,t)},d))},r))})]})},a);case"list":{const u=n.ordered?"ol":"ul";return e.jsx(u,{className:`m-0 flex flex-col text-sm text-content-muted ${i&&n.ordered?"list-none gap-2 p-0":`gap-1.5 pl-5 ${n.ordered?"list-decimal":"list-disc"}`}`,children:n.items.map((r,s)=>{const d=r.match(/^\[([ xX])\]\s+(.*)$/);return d?e.jsxs("li",{className:"list-none -ml-5 flex items-start gap-2",children:[e.jsx("span",{"aria-hidden":!0,className:`mt-0.5 grid place-items-center w-4 h-4 shrink-0 rounded border text-[0.625rem] ${d[1]===" "?"border-border-strong text-transparent":"border-emerald-400/60 bg-emerald-500/15 text-emerald-300"}`,children:"✓"}),e.jsx("span",{children:y(d[2],`${a}i${s}`,t)})]},s):i&&n.ordered?e.jsxs("li",{className:"flex gap-3 rounded-lg border border-border bg-app px-3 py-3 leading-relaxed",children:[e.jsx("span",{"aria-hidden":!0,className:"grid h-6 w-6 shrink-0 place-items-center rounded-md bg-indigo-500/15 font-mono text-[0.6875rem] font-bold text-indigo-300",children:String(s+1).padStart(2,"0")}),e.jsx("span",{children:y(r,`${a}i${s}`,t)})]},s):e.jsx("li",{children:y(r,`${a}i${s}`,t)},s)})},a)}default:return e.jsx("p",{className:"m-0 text-sm text-content-muted leading-relaxed",children:y(n.body,a,t)},a)}}function $({source:n,variant:o="default",resolveLink:i}){const t=W(n||""),a=t.filter(r=>r.t==="h2"),u=U(a.map(r=>r.body));if(a.forEach((r,s)=>{r.headingId=u[s]}),o==="guide"){const r=t.filter((h,l)=>!(l===0&&h.t==="h1")),s=[],d=[];let m=null;return r.forEach((h,l)=>{h.t==="h2"?(m={heading:h,blocks:[],index:l},d.push(m)):m?m.blocks.push({block:h,index:l}):h.t!=="hr"&&s.push({block:h,index:l})}),e.jsxs("div",{className:"flex max-w-none flex-col gap-4",children:[s.length>0&&e.jsx("div",{className:"flex flex-col gap-3 rounded-xl border border-indigo-400/20 bg-gradient-to-br from-indigo-500/10 via-surface to-surface px-4 py-4 sm:px-5",children:s.map(({block:h,index:l})=>k(h,l,!0,i))}),d.map(({heading:h,blocks:l,index:f})=>e.jsxs("section",{id:h.headingId,className:"scroll-mt-24 rounded-xl border border-border bg-surface px-4 py-4 shadow-sm shadow-black/10 sm:px-5 sm:py-5",children:[e.jsxs("div",{className:"mb-4 flex items-start gap-3 border-b border-border pb-3",children:[e.jsx("span",{"aria-hidden":!0,className:"mt-1 h-5 w-1 shrink-0 rounded-full bg-gradient-primary"}),k(h,f,!0,i)]}),e.jsx("div",{className:"flex flex-col gap-3",children:l.map(({block:b,index:w})=>k(b,w,!0,i))})]},h.headingId))]})}return e.jsx("div",{className:"flex max-w-none flex-col gap-3",children:t.map((r,s)=>k(r,s,!1,i))})}const q=`# Step 1: Open Prep My Avatar

Prep My Avatar runs on your computer and opens in a web browser. You do not need an API key, a graphics card, or any AI tools to open it and begin reviewing photos.

## Before you begin

You need a Windows, macOS, or Linux computer and an internet connection for the first installation. Keep five or more clear photos ready for your first test. Use photos you own or have permission to process.

## Do this

### Windows

1. Download or clone the repository and extract it if it arrived as a ZIP file.
2. Open the extracted \`prep-my-avatar\` folder.
3. Double-click \`start.bat\`.
4. Leave the terminal window open while you use the app.

### macOS or Linux

1. Open the Terminal application.
2. Type \`cd \`, including the space, drag the \`prep-my-avatar\` folder into the Terminal window, and press Enter.
3. Run these commands one line at a time:

\`\`\`bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
python backend/source_launcher.py --install --root . --data-dir data
python data/source-launcher.py --root . --data-dir data
\`\`\`

4. Leave Terminal open. Open <http://127.0.0.1:5050/> if the browser does not open automatically.

The repository README has the canonical [Installation and launch](https://github.com/Kevinjohn/prep-my-avatar#installation-and-launch) instructions, including later launches and Docker.

## You are finished when

Your browser shows **Welcome to Prep My Avatar** or the **Setup** screen. On first launch, choose **Start setup**. All five setup steps are optional; the next five pages explain them one at a time.

If the page does not open, keep the terminal visible and use the error message with the **Troubleshooting** reference in this guide.
`,Y=`# Step 2: Choose an image provider

This optional setup page enables the app to create new images for missing poses or framings. You can use imported photos and export a dataset without configuring any provider.

## Before you begin

Choose at most one provider for your first test. Provider accounts and API use may cost money. A key is a private password: paste it only into the labelled field and never put it in screenshots or support reports.

- **Gemini API key** uses Nano Banana through Google.
- **Replicate API token** uses Nano Banana through Replicate.
- **OpenAI API key** uses ChatGPT image generation.
- Local Klein is configured on the next page instead of using one of these keys.

## Do this

1. On **Step 1 of 5 — Image generation**, open the account link beside your chosen provider.
2. Sign in to that provider, create a key or token, and copy it.
3. Paste it into the matching field: **Gemini API key**, **Replicate API token**, or **OpenAI API key**.
4. Select **Save & test** beside that field.
5. Wait for a successful connection result.
6. Select **Save & continue →**.

If you do not want remote generation, leave every field empty and select **Save & continue →**. You can add a provider later under **Settings → Image engines**.

## You are finished when

Your chosen key shows **Saved** and its test succeeds, or you have deliberately left all keys empty. The wizard then shows **Step 2 of 5 — Local generation — ComfyUI**.
`,z=`# Step 3: Configure ComfyUI

ComfyUI is optional. It enables local FLUX.2 Klein image generation and the Test Studio. Skip it if you only want to import photos, use a remote image provider, or export data for another tool.

## Before you begin

Local image generation needs a compatible GPU, a separate ComfyUI installation, and large model downloads. Installing Prep My Avatar does not install ComfyUI automatically.

## Do this

1. On **Step 2 of 5 — Local generation — ComfyUI**, check whether the page says ComfyUI is already running.
2. If it is not installed, follow the **ComfyUI on GitHub** link, install it, and start it. Its usual address is \`http://127.0.0.1:8188\`.
3. Enter the **ComfyUI install directory** and **ComfyUI API URL** shown by your installation.
4. Select **Save & re-check**. The directory is valid only when it contains ComfyUI's \`main.py\` file and \`models\` folder.
5. If you want local Klein generation, accept the model licence, add any required Hugging Face token in Settings, and use the offered model, text-encoder, VAE, and consistency-LoRA downloads.
6. Select **Save & continue →**.

To skip this step, leave the fields unchanged and continue. You can return through **Setup** or **Settings → Local tools**.

## You are finished when

The page reports that ComfyUI is running at the configured URL, or you have deliberately skipped local generation. The wizard then shows the local-vision step.
`,X=`# Step 4: Configure local vision

Local vision can classify your photos, map coverage, and write first-draft captions without sending those photos to a remote captioning service. You may use **Ollama**, **LM Studio**, or **llama.cpp**.

## Before you begin

This step is optional. Each choice needs a running local server and a vision-capable, or “multimodal,” model. A text-only model cannot inspect images.

## Do this

1. On **Step 3 of 5 — Local vision**, open **Local vision backend**.
2. Choose one backend:
   - **Ollama:** install and start Ollama, keep the default URL unless you changed it, then pull the model offered by the wizard.
   - **LM Studio:** start its local server, load a vision model, and use its OpenAI-compatible URL, normally \`http://127.0.0.1:1234/v1\`.
   - **llama.cpp:** start \`llama-server\` with a vision model and projector, then use its OpenAI-compatible URL, normally \`http://127.0.0.1:8080/v1\`.
3. Enter the exact loaded model identifier in the **vision model** field.
4. Select **Save & re-check**.
5. Correct the URL or loaded model if the check fails, then re-check.
6. Select **Save & continue →**.

To skip automatic analysis and captioning, continue without configuring a backend. You can classify photos and edit captions manually.

## You are finished when

The page says the selected backend is running and its vision model is loaded, or you have deliberately skipped local vision. The wizard then shows **Quality tools — ML extras**.
`,_=`# Step 5: Install quality tools

The optional quality tools add face-similarity scoring, person masks, and watermark inpainting. They help you make decisions; they do not delete images automatically.

## Before you begin

These extras support Python 3.11 or 3.12. If the page warns that your Python version is unsupported, skip this step for now. The core workflow still works.

## Do this

1. On **Step 4 of 5 — Quality tools — ML extras**, read the three tool cards.
2. Select **Install** only for the tools you want:
   - **Face-similarity scoring** compares a face with your reference.
   - **Person masks** reduce how strongly training learns the background.
   - **Watermark inpainting** can repair some small off-centre watermarks.
3. Wait until each selected card says **Installed**. Use **Reinstall** only to repair an existing installation.
4. Alternatively, expand **install everything at once** and use **Install all (pip)**.
5. Select **Save & continue →**.

If an installation fails, copy the visible error before leaving the page. You can retry later from **Setup**.

## You are finished when

Every tool you chose says **Installed**, or you have deliberately skipped all three. The wizard then shows **LoRA training — ai-toolkit**.
`,H=`# Step 6: Configure training

ai-toolkit trains a LoRA on your own computer. It is optional: you can export a training ZIP for another trainer or configure vast.ai for cloud training later.

## Before you begin

Local training requires a compatible GPU and a separate ai-toolkit installation. Cloud training requires a vast.ai account, API key, account credit, and spending limits configured under Settings.

## Do this

1. On **Step 5 of 5 — LoRA training — ai-toolkit**, check whether the app found an installation.
2. If it found one, select **Use this ai-toolkit →**.
3. Otherwise, follow **ai-toolkit on GitHub**, clone and install it according to its README, then return to Prep My Avatar.
4. Enter the **ai-toolkit directory**. This is the folder containing that separate installation.
5. Select **Save & re-check**.
6. When the path is valid, select **Save & finish →**.

To skip training setup, leave the directory empty and finish. For cloud training later, add a **vast.ai API key** and safety limits in **Settings → Training → Cloud training**.

## You are finished when

The page says ai-toolkit is set up, or you have deliberately skipped it, and the setup summary appears. Review the summary, then continue to **Datasets**.
`,Z=`# Step 7: Create a dataset

A dataset is one project containing source images, decisions, captions, and training settings. For a first run with photos of yourself, create a **Character** dataset.

## Before you begin

Decide what the images teach:

- **Character** teaches a person or face and uses a trigger word in prompts.
- **Concept** teaches an object, action, effect, or idea.
- **Style** teaches a visual aesthetic and does not need a prompt trigger.

## Do this

1. Select **Datasets** in the top navigation.
2. Select **+ New dataset** if the **New dataset** form is not already open.
3. Choose **Character**, **Concept**, or **Style**.
4. Enter a clear project name.
5. For Character or Concept, enter a distinctive trigger word such as \`zchar_alex\`. Do not use a common word such as \`person\`.
6. For Concept, describe exactly what the captions must leave out.
7. Choose the target model family. If you do not know which one you need, keep the default; you can change it later.
8. Leave advanced fidelity choices at their defaults for a first test.
9. Select **Create**.

The remaining first-run pages use a **Character** dataset because it exposes every guided Progress step. If you chose **Concept** or **Style**, keep following the pages: each Character-only page now tells you what is hidden and what to do instead.

## You are finished when

The new dataset workspace opens and its name appears at the top. The left side shows the dataset sections and, for a Character dataset, a **Progress** checklist beginning with **Import corpus**.
`,V=`# Step 8: Import your photos

Start with real source images. The app preserves each original and makes a working copy, so later crops and decisions do not overwrite your source file.

## Before you begin

For a Character dataset, gather at least five clear photos you own or have permission to use. Include different angles and framings if possible. Avoid beginning with many nearly identical selfies. Five photos are enough to test the workflow, not necessarily enough for a final LoRA.

## Do this

1. Open **Add images** in the dataset sidebar.
2. Find the import area at the top of the page.
3. Drag image files into it, or select the area and choose files from your computer.
4. Leave automatic head crop off for the first import unless you specifically need face-only crops.
5. Wait until processing finishes. Do not close the app while the busy message is visible.
6. Check the import result. Exact duplicates are skipped; near-duplicates remain available for your review.

For Concept or Style datasets, import representative examples of the concept or style. Concept datasets can also use the scraper, but a manual import is the simplest first test.

## You are finished when

The **Progress** checklist marks **Import corpus** complete and reports the number imported. The **Corpus Workbench** shows the new images as needing a decision.
`,J=`# Step 9: Review the imported corpus

Review decides which imported images are allowed into the training set and records what each image contributes. Imported images begin as **Needs decision** and do not train until you accept them.

## Before you begin

Stay in **Add images** and find **Corpus Workbench**. If local vision is ready, it can propose classifications. Without local vision, use the manual controls.

## Do this

1. Select **Refresh local analysis**. This checks basic image quality and duplicates.
2. For a Character dataset, select **Map visual coverage** when local vision is available, or open each image's manual editor. Concept and Style datasets do not show Character visual-coverage controls; review their technical analysis and training admission instead.
3. For a Character dataset, record framing, angle, expression, lighting, pose, background, and occlusion where the app asks for them.
4. Inspect warnings instead of accepting them blindly. A warning is evidence to review, not an automatic rejection.
5. Select **✓ Accept** for usable images and **✕ Reject** for images that should not train.
6. Use **Accept clean** only after checking the set it will affect.
7. Record source rights and consent when the workbench requests them.

Reject blurred, unusable, or incorrect-subject images. Keep useful variety even when a photo is not aesthetically perfect.

## You are finished when

For Character, the **needs decision** and **needs coverage** counts are zero and Progress shows **Review corpus — mapped**. For Concept or Style, every imported image has an intentional **Accept** or **Reject** decision.
`,Q=`# Step 10: Choose identity anchors

Anchors are the small set of reviewed photos that a remote image provider may receive with a generation request. They help generated candidates keep the correct identity.

This is a Character-only step. Concept and Style datasets do not show anchor controls; if you chose either kind, skip this page.

## Before you begin

Use only accepted, identity-accurate Character photos. An anchor should have a clear face, useful detail, and a viewpoint that adds something different from the other anchors.

## Do this

1. In **Corpus Workbench**, filter to accepted images if necessary.
2. Leave strong ordinary candidates on **Automatic** so the app can choose a bounded set for each request.
3. Select **📌 Pin** for a small number of identity-critical photos that must always be considered.
4. Select **⊘ Exclude** for any photo that must never be sent to a remote provider. Excluding it from API use does not remove it from local training.
5. Avoid pinning several near-identical photos; varied angles provide better evidence.
6. Check the **anchors/request** and **pinned** counts in the workbench summary.

If you use only local tools or never generate images, you may leave every accepted image on Automatic.

## You are finished when

For Character, Progress shows a selected total or you have deliberately kept the automatic selection, and no private photo is eligible for API use. For Concept or Style, the step is finished because the controls do not apply.
`,ee=`# Step 11: Review the coverage plan

Coverage describes what evidence your accepted images provide: face, bust, body, and back views, plus useful variation in angle, expression, lighting, pose, and background.

Character datasets show this detailed visual plan. Concept and Style datasets instead show **Concept coverage & admission** or **Style coverage & admission**, which checks accepted-image count and basic readiness without identity anchors or generated pose gaps.

## Before you begin

Finish classifying and accepting the imported corpus first. An unclassified image is shown as **unknown**; unknown does not mean the view is missing.

## Do this

1. In **Add images**, scroll to **Coverage plan**, **Concept coverage & admission**, or **Style coverage & admission**, depending on the dataset kind.
2. For Concept or Style, read the admission cards and add or accept more varied examples where a card is weak; then continue to Step 14 because Steps 12 and 13 are Character-only.
3. For Character, keep **Balanced** for a normal first run. **Strict** recommends fewer generated gaps; **Experimental** allows more.
4. Read each framing card. The first number is what you have and the second is the target.
5. Expand the other dimensions to see weak, missing, covered, and unknown evidence.
6. Adjust a target only when your intended output genuinely needs a different balance.
7. Select **Save targets** after changing the profile or any number.
8. Add another real photo whenever practical. Treat generated gap shots as optional supplements, not replacements for unknown imports.

## You are finished when

For Character, you understand the gaps and the selected profile is saved. For Concept or Style, you have reviewed the admission cards. If Character gaps remain and generation is configured, **Review gap shots** appears; otherwise continue to curation.
`,te=`# Step 12: Set a primary reference

The primary reference is used by local FLUX.2 Klein and by optional face-similarity scoring. Remote API engines can use the reviewed anchor set instead.

This is a Character-only step. Concept and Style datasets do not show a primary-reference control; if you chose either kind, skip this page.

## Before you begin

Skip this page only if you will use neither local Klein nor face-similarity scoring. Otherwise, choose a sharp, accepted image with an unobstructed face and a neutral enough angle to identify the person reliably.

## Do this

1. Open **Add images** and find **optional primary reference** below the coverage plan.
2. Select or drop the best reference photo.
3. Open the crop control and keep the face clear without cutting off important features.
4. Add up to three extra references only when another angle adds useful identity evidence.
5. Remove any weak or incorrect extra reference.
6. Confirm the preview shows the intended person and no unrelated face dominates the frame.

The reference is not automatically your entire training set. It is an identity input for local Klein and face scoring; accepted images still determine what is available for training.

## You are finished when

For Character, Progress shows **Primary reference — set**, or you have deliberately skipped both features that need it. For Concept or Style, the step is finished because it does not apply.
`,ne=`# Step 13: Generate missing views

Generation is optional. Use it only for real coverage gaps that you cannot fill with suitable source photos. Generated images are candidates and never enter training until you accept them.

This guided gap generator is Character-only. Concept and Style datasets do not show it; add more examples with **Import**, or use the Concept scraper when appropriate, then continue to curation.

## Before you begin

You need a tested Gemini, Replicate, or OpenAI credential, or a working local Klein setup. Before remote generation, explicitly enable remote-generation privacy in **Settings → Image engines**. Remote providers may charge per request and receive the prompt plus the bounded anchor pack.

## Do this

1. In **Coverage plan**, select **Review gap shots**, or open the generation panel under **Add images**.
2. Review the recommended shots. Remove any shot you do not actually need.
3. Choose the configured engine and model.
4. Keep the multiplier at one for the first attempt.
5. Read the estimated request count and cost information.
6. Start generation and wait for the results. Use **Stop generation** if early results show that the prompt or identity is wrong.
7. Use the edit control on an individual result to correct its prompt and regenerate that shot only.

## You are finished when

For Character, every requested generation has completed or been stopped and each result awaits review. For Concept or Style, the step is finished after you deliberately use import or the Concept scraper instead.
`,ae=`# Step 14: Curate the images

Curation creates the final kept set. Only images marked with a check are included in captions, export, and training.

## Before you begin

Open **Images** for the full grid or **Curation** for focused review tools. Judge identity, sharpness, composition, duplicates, watermarks, and usefulness—not just whether an image looks attractive.

## Do this

1. Open each undecided image at full size when the thumbnail is not enough.
2. Select **✓** to keep a useful image or **✕** to reject it.
3. Reject generated images that do not resemble the intended person.
4. Remove near-duplicates unless each one contributes meaningfully different evidence.
5. Use the crop tool only when it improves framing without removing important context.
6. Resolve every reconstruction or rescue comparison by choosing one version or neither. Never keep both sides of an exclusive pair.
7. Watch the composition meter and add real variety where it is weak.
8. Use curation history if you need to undo a recent keep or reject decision.

## You are finished when

No image says it is awaiting a decision, every comparison is resolved, and at least one image is kept. The Progress item **Curate** is checked.
`,oe=`# Step 15: Caption the kept images

A caption tells the training model what is visible in each image. The thing you are teaching must be left out: Character captions omit identity traits, Concept captions omit the concept, and Style captions describe content rather than the visual style.

## Before you begin

Keep and reject images before captioning. Automatic captioning needs a ready local-vision backend. Without one, you can type captions manually on each kept image.

## Do this

1. Open **Captions** in the dataset sidebar.
2. Confirm the caption style. Use prose for the prose-based model families; use booru tags for an SDXL booru workflow.
3. Select **Caption the kept ones** and wait for the count to finish.
4. Read every caption. Correct factual mistakes and remove descriptions of the training target.
5. Open the identity- or concept-leak badge and fix every highlighted caption.
6. Use **Caption tools** for a repeated find-and-replace across the set.
7. If another trainer needs sidecar files, use **Write .txt files** after the captions are final.

## You are finished when

The kept count and captioned count match, every caption is accurate, and the leak check reports no unresolved target descriptions. The Progress item **Caption** is checked.
`,se=`# Step 16: Score face similarity

Face scoring is an optional review aid for Character datasets. It compares each kept face with the reference and shows which images deserve closer inspection. A score is not permission to keep or delete an image automatically.

## Before you begin

This page applies only when **Face-similarity scoring** was installed during Setup and a suitable reference photo is set. Skip it for Concept or Style datasets.

## Do this

1. Open **Curation**.
2. Select **Analyze faces**.
3. Wait for every kept image to receive a result. ComfyUI may pause while this local analysis uses the GPU or CPU.
4. Review low or orange results at full size. Check whether the face is actually wrong, obscured, too small, or simply seen from a difficult angle.
5. Reject an off-identity image manually. Keep a useful image when your own inspection shows the score is misleading.
6. Review sharpness and exposure warnings separately; identity and technical quality are different questions.

## You are finished when

Every kept Character image you intended to score has a result and every suspicious result has been reviewed. The optional Progress item **Score** is checked.
`,ie=`# Step 17: Export the dataset

Export creates a standard training package from the images currently marked **kept**. It does not include rejected or undecided images.

## Before you begin

Finish curation and captions first. An export can be useful even if you never train inside Prep My Avatar.

## Do this

1. Check the kept count beside **Export ZIP** at the top of the dataset.
2. Open **Import & export** if you want to review the export options, or use the top **Export ZIP** button directly.
3. Select **Export ZIP**.
4. Choose a destination folder if your browser asks.
5. Wait for the download to finish, then open the ZIP to verify it contains image files and matching \`.txt\` caption files.
6. Keep \`_prep_my_avatar_manifest.json\`. Training tools can ignore it, but it records the source mix, coverage, and provenance.

An export ZIP is a training package, not a complete backup of the project. The final guide step explains the separate **Backup** action.

## You are finished when

A ZIP file exists in your chosen download folder and its image/text pairs match the kept set. If export is your goal, you can stop here and use the ZIP with a compatible external trainer.
`,re=`# Step 18: Train a LoRA

Training turns the kept images and captions into a \`.safetensors\` LoRA for one model family. This optional step can use configured local ai-toolkit or a vast.ai cloud worker.

## Before you begin

Training can take significant time, disk space, GPU memory, and—for cloud runs—money. Complete curation, captions, leak review, and source-rights confirmation. Accept any required base-model licence and add its Hugging Face token before launch.

## Do this

1. Open **Training** in the dataset sidebar.
2. Choose the LoRA family that matches the target model you intend to use.
3. Read the readiness summary and resolve blocking findings.
4. Keep the automatic step count and default recipe for a first run. Open **Advanced options** only when you understand the setting you need to change.
5. Select **Train the LoRA** for the configured local trainer, or **Train in cloud**.
6. Read the **Before training** confirmation. Fix duplicate pairs or caption leaks shown there.
7. Confirm the launch. For cloud training, check the quoted limits before accepting.
8. Keep the app running for local training. Follow either type of run from **Runs**.

## You are finished when

The run reaches **Finished** and at least one checkpoint appears. If it fails, open the run log, keep the exact error, fix that cause, and use retry rather than starting several duplicate cloud jobs.
`,ce=`# Step 19: Review training checkpoints

A checkpoint is a saved LoRA from a particular point during training. The last checkpoint is not automatically the best; an earlier one may preserve identity while responding more flexibly to prompts.

## Before you begin

Wait for training to produce checkpoints. Face scoring is helpful but optional. Do not delete intermediate checkpoints until you have compared their outputs.

## Do this

1. Open **Checkpoints & LoRAs** in the dataset sidebar.
2. Choose the model family and training base used by the run.
3. Review the visible step and dataset-version badges. Select **Run folder** to inspect that run's raw checkpoints, sample images, training log, and other files.
4. If face scoring is available, run the checkpoint scoring action and treat its winner as a candidate—not a final decision.
5. Keep the checkpoints you want to test in Studio.
6. Select **Import →** on each checkpoint you want to test. This copies the raw run checkpoint into the labelled ComfyUI LoRA folder; a checkpoint left only in the run folder is not available to Studio.
7. Wait for the imported state to appear, then use **LoRA folder** if you want to verify the copied file.
8. Move an unwanted checkpoint to Trash only after you are sure it is not needed.
9. Use the cleanup action only after a best checkpoint has been established; it keeps the final and any scored winner described by the UI.

## You are finished when

You have identified the small set worth testing, know which run produced each one, and imported at least one compatible checkpoint into ComfyUI for Studio.
`,le=`# Step 20: Test the LoRA in Studio

Studio compares checkpoints and strengths with the same prompts and seeds. This separates the effect of the LoRA from random changes between generated images.

## Before you begin

Studio needs a working ComfyUI setup, compatible base models and nodes, and at least one checkpoint. If **Studio** is unavailable in Progress, return to Setup and configure ComfyUI.

## Do this

1. Open **Studio** from the dataset or the top navigation.
2. Select the correct model family.
3. Choose one or more compatible checkpoints.
4. Enter a plain test prompt that includes the Character or Concept trigger word when one is required.
5. Keep the suggested strengths and fixed seed for the first comparison.
6. Run the test grid.
7. Compare identity, prompt obedience, artefacts, and flexibility across rows and strengths.
8. Vote or rate the results, then star the best settings.
9. Repeat with a different prompt before making a final choice.

## You are finished when

The dataset has starred **best settings** backed by more than one useful prompt. Record or download the winning checkpoint and strength for the image-generation workflow where you will use it.
`,de=`# Step 21: Back up the project

A portable backup preserves the dataset itself: originals, working images, captions, settings, relationships, decisions, and provenance. It is different from the smaller training export ZIP.

## Before you begin

Choose a storage location outside the app's data folder, such as an external drive or a backed-up folder. Treat the backup as sensitive because it contains the original images.

## Do this

1. Open the dataset's **Import & export** section.
2. Select **Backup**.
3. Save the backup ZIP outside the Prep My Avatar data directory.
4. Wait for the download to finish and confirm the file is not empty.
5. Keep at least one second copy if losing the project would matter.
6. To prove recovery before deleting or moving the original installation, return to **Datasets**, choose **Restore backup**, and restore the ZIP. Restore creates a new dataset rather than overwriting the existing one.
7. Delete the temporary restored copy only after comparing it with the original. Deleted datasets first move to **Settings → Maintenance → Trash**.

## You are finished when

The portable backup exists in a separate safe location and, for important work, has been restored successfully once. Your first complete run is now finished; use the reference pages for deeper dataset choices, troubleshooting, and support.
`,he=`# Building a good LoRA dataset

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

The Corpus workbench labels local technical analysis as **not analyzed** when no
technical pass exists, **outdated** for the older whole-frame scoring, and
**current** for version 2 or newer. Version 2 measures sharpness region by region,
so a focused subject against a deliberately blurred background is not penalized
as though the whole photo were soft. Analysis is never upgraded merely by opening
or viewing a dataset. Use **Refresh local analysis** explicitly to apply the
bokeh-aware score; the refresh preserves face analysis, coverage, source-rights,
and review decisions.

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
`,pe=`# Troubleshooting

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
`,ue=`# Getting help & reporting problems

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
`,p=(n,o,i,t,a)=>({id:n,num:o,title:i,description:t,source:a,group:"First run"}),x=[p("getting-started","01","Open the app","Install and launch Prep My Avatar, then begin the five-page Setup wizard.",q),p("image-provider","02","Choose an image provider","Optionally connect Gemini, Replicate, or OpenAI for remote image generation.",Y),p("comfyui","03","Configure ComfyUI","Optionally enable local Klein generation and Test Studio.",z),p("local-vision","04","Configure local vision","Optionally connect Ollama, LM Studio, or llama.cpp for image analysis and captions.",X),p("quality-tools","05","Install quality tools","Optionally add face scoring, person masks, and watermark repair.",_),p("training-tools","06","Configure training","Optionally connect ai-toolkit for local LoRA training.",H),p("create-dataset","07","Create a dataset","Create a Character, Concept, or Style project with the right target model.",Z),p("import-photos","08","Import your photos","Add the real source images that form the authoritative corpus.",V),p("review-corpus","09","Review the corpus","Classify, accept, or reject every imported image.",J),p("choose-anchors","10","Choose identity anchors","Control which accepted photos may anchor generation requests.",Q),p("plan-coverage","11","Review coverage","Identify useful evidence, unknown images, and genuine gaps.",ee),p("primary-reference","12","Set a primary reference","Optionally choose the identity image used by local Klein and face-similarity scoring.",te),p("generate-gaps","13","Generate missing views","Optionally create candidates for proven coverage gaps.",ne),p("curate-images","14","Curate the images","Keep the useful images, reject the rest, and resolve every comparison.",ae),p("caption-images","15","Caption the kept images","Generate or write accurate captions and remove target leaks.",oe),p("score-images","16","Score face similarity","Optionally use face scores to find Character images that need review.",se),p("export-dataset","17","Export the dataset","Download standard image and caption pairs for another trainer.",ie),p("train-lora","18","Train a LoRA","Optionally launch a local or cloud training run.",re),p("review-checkpoints","19","Review checkpoints","Keep the checkpoints worth comparing and trace each to its run.",ce),p("test-studio","20","Test in Studio","Compare checkpoints and strengths with controlled prompts and seeds.",le),p("back-up","21","Back up the project","Create and verify a portable backup of the complete dataset.",de)],R=[{id:"dataset-guide",num:"R1",title:"Building a good dataset",description:"Understand the reasoning behind image, caption, training, and checkpoint choices.",source:he,group:"Reference"},{id:"troubleshooting",num:"R2",title:"Troubleshooting",description:"Find a symptom, understand the cause, and apply the shortest reliable fix.",source:pe,group:"Reference"}],P=[...x,...R],L={id:"getting-help",num:"R3",title:"Getting help",description:"Create a useful report and share the details needed to solve a problem.",source:ue,group:"Support",extra:"diagnostic"},we=[...P,L],me=Object.freeze({"getting-started.md":"/guide/getting-started","using-the-app.md":"/guide/getting-started","steps/02-image-provider.md":"/guide/image-provider","steps/03-comfyui.md":"/guide/comfyui","steps/04-local-vision.md":"/guide/local-vision","steps/05-quality-tools.md":"/guide/quality-tools","steps/06-training-tools.md":"/guide/training-tools","steps/07-create-dataset.md":"/guide/create-dataset","steps/08-import-photos.md":"/guide/import-photos","steps/09-review-corpus.md":"/guide/review-corpus","steps/10-choose-anchors.md":"/guide/choose-anchors","steps/11-plan-coverage.md":"/guide/plan-coverage","steps/12-primary-reference.md":"/guide/primary-reference","steps/13-generate-gaps.md":"/guide/generate-gaps","steps/14-curate-images.md":"/guide/curate-images","steps/15-caption-images.md":"/guide/caption-images","steps/16-score-images.md":"/guide/score-images","steps/17-export-dataset.md":"/guide/export-dataset","steps/18-train-lora.md":"/guide/train-lora","steps/19-review-checkpoints.md":"/guide/review-checkpoints","steps/20-test-studio.md":"/guide/test-studio","steps/21-back-up.md":"/guide/back-up","../DATASET_GUIDE.md":"/guide/dataset-guide","troubleshooting.md":"/guide/troubleshooting","getting-help.md":"/help"}),ge=n=>{const o=me[n];return o?`#${o}`:null},T=(n,o)=>`${n==="getting-help"?"/help":`/guide/${n}`}?heading=${encodeURIComponent(o)}`,fe=(n,o)=>{if(!n||!o)return;const i=n.getBoundingClientRect(),t=o.getBoundingClientRect();t.top<i.top?n.scrollTop-=i.top-t.top:t.bottom>i.bottom&&(n.scrollTop+=t.bottom-i.bottom)};function ve({helpOnly:n=!1}){const{section:o}=O(),i=D(),t=B(),a=n?[L]:P,u=o||"getting-started",r=n?0:a.findIndex(c=>c.id===u),s=n||r>=0,d=v.useRef(null),m=v.useRef(null),h=v.useRef(null),l=s?a[r]:a[0],f=r>0?a[r-1]:null,b=r<a.length-1?a[r+1]:null,w=M(l.source),F=Math.max(1,Math.ceil(l.source.trim().split(/\s+/).length/210)),S=x.findIndex(c=>c.id===l.id),j=(c,g)=>{c.preventDefault(),i(T(l.id,g),{replace:!0})};if(v.useEffect(()=>{var N;if(!s)return;const c=new URLSearchParams(t.search).get("heading"),g=c?document.getElementById(c):null;if(!g){window.scrollTo(0,0),(N=d.current)==null||N.focus();return}g.tabIndex=-1,g.focus({preventScroll:!0});const C=window.matchMedia("(prefers-reduced-motion: reduce)").matches;g.scrollIntoView({behavior:C?"auto":"smooth",block:"start"})},[l.id,t.search,s]),v.useEffect(()=>{fe(m.current,h.current)},[l.id]),!s)return e.jsx(E,{to:"/guide/getting-started",replace:!0});const A=c=>{const g=c.id===l.id,C=`relative flex w-full items-baseline gap-2.5 rounded-md px-3 py-2 text-left text-sm ${g?"bg-surface-raised text-content":"text-content-muted hover:bg-surface hover:text-content"}`;return e.jsxs(I,{to:`/guide/${c.id}`,ref:g?h:void 0,"aria-current":g?"page":void 0,className:C,children:[g&&e.jsx("span",{"aria-hidden":!0,className:"absolute bottom-1.5 left-0 top-1.5 w-0.5 rounded bg-gradient-primary"}),e.jsx("span",{className:`font-mono text-[11px] ${g?"text-content":"text-content-subtle"}`,children:c.num}),e.jsx("span",{className:"font-medium",children:c.title})]},c.id)};return e.jsxs("div",{className:n?"mx-auto max-w-5xl xl:grid xl:grid-cols-[minmax(0,1fr)_190px] xl:items-start xl:gap-7":"lg:grid lg:grid-cols-[210px_minmax(0,1fr)] lg:items-start lg:gap-7 xl:grid-cols-[210px_minmax(0,1fr)_190px]",children:[!n&&e.jsxs("aside",{children:[e.jsxs("nav",{"aria-label":"Guide chapters",className:"pb-3 lg:hidden",children:[e.jsx("label",{htmlFor:"guide-page",className:"mb-1 block font-mono text-[11px] uppercase tracking-[0.18em] text-content-subtle",children:"Guide page"}),e.jsxs("select",{id:"guide-page","aria-label":"Guide page",value:l.id,onChange:c=>i(`/guide/${c.target.value}`),className:"w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-content",children:[e.jsx("optgroup",{label:"First run",children:x.map(c=>e.jsxs("option",{value:c.id,children:[c.num," — ",c.title]},c.id))}),e.jsx("optgroup",{label:"Reference",children:R.map(c=>e.jsxs("option",{value:c.id,children:[c.num," — ",c.title]},c.id))})]})]}),e.jsxs("nav",{ref:m,"aria-label":"Guide chapters",className:"hidden lg:sticky lg:top-20 lg:block lg:max-h-[calc(100vh-6rem)] lg:overflow-y-auto lg:pr-1",children:[e.jsx("p",{className:"px-3 pb-2 font-mono text-[11px] uppercase tracking-[0.18em] text-content-subtle",children:"First run"}),e.jsx("div",{className:"flex flex-col gap-0.5",children:x.map(A)}),e.jsx("p",{className:"mt-4 px-3 pb-2 font-mono text-[11px] uppercase tracking-[0.18em] text-content-subtle",children:"Reference"}),e.jsx("div",{className:"flex flex-col gap-0.5",children:R.map(A)})]})]}),e.jsxs("section",{className:`min-w-0 max-w-4xl pb-10 ${n?"mx-auto":"mt-2 lg:mt-0"}`,children:[e.jsxs("header",{className:"relative mb-4 overflow-hidden rounded-2xl border border-border bg-surface px-5 py-5 sm:px-6 sm:py-6",children:[e.jsx("div",{"aria-hidden":!0,className:"absolute -right-16 -top-20 h-52 w-52 rounded-full bg-indigo-500/10 blur-3xl"}),e.jsxs("div",{className:"relative",children:[e.jsxs("div",{className:"mb-3 flex flex-wrap items-center gap-2 font-mono text-[0.6875rem] uppercase tracking-[0.14em] text-content-subtle",children:[e.jsx("span",{className:"rounded-md border border-indigo-400/30 bg-indigo-500/10 px-2 py-1 text-indigo-300",children:n?"Support":S>=0?`Step ${l.num}`:"Reference"}),e.jsxs("span",{children:[F," min read"]}),S>=0&&e.jsxs(e.Fragment,{children:[e.jsx("span",{"aria-hidden":!0,children:"·"}),e.jsxs("span",{children:[S+1," of ",x.length]})]})]}),e.jsx("h1",{ref:d,tabIndex:-1,className:"m-0 max-w-2xl text-2xl font-bold tracking-tight text-content focus:outline-none sm:text-3xl",children:l.title}),e.jsx("p",{className:"mb-0 mt-2 max-w-2xl text-sm leading-relaxed text-content-muted sm:text-base",children:l.description})]})]}),w.length>0&&e.jsxs("nav",{"aria-label":"On this page",className:"mb-4 rounded-xl border border-border bg-surface p-3 xl:hidden",children:[e.jsx("p",{className:"m-0 mb-2 font-mono text-[0.625rem] uppercase tracking-[0.16em] text-content-subtle",children:"On this page"}),e.jsx("div",{tabIndex:0,className:"flex gap-2 overflow-x-auto pb-0.5",children:w.map(c=>e.jsx("a",{href:`#${T(l.id,c.id)}`,onClick:g=>j(g,c.id),className:"shrink-0 rounded-full border border-border bg-transparent px-2.5 py-1 text-xs text-content-muted hover:border-border-strong hover:text-content",children:c.title},c.id))})]}),e.jsx($,{source:l.source,variant:"guide",resolveLink:ge}),l.extra==="diagnostic"&&e.jsx("div",{className:"mt-6",children:e.jsx(G,{})}),!n&&e.jsxs("div",{className:"mt-6 grid grid-cols-2 gap-3 border-t border-border pt-4",children:[f?e.jsxs(I,{to:`/guide/${f.id}`,className:"group flex min-w-0 items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2.5 no-underline hover:bg-surface-raised",children:[e.jsx("span",{"aria-hidden":!0,className:"text-content-subtle",children:"←"}),e.jsxs("span",{className:"min-w-0",children:[e.jsx("span",{className:"block font-mono text-[0.625rem] uppercase tracking-wider text-content-subtle",children:"Previous"}),e.jsx("span",{className:"block truncate text-sm font-medium text-content-muted group-hover:text-content",children:f.title})]})]}):e.jsx("span",{}),b?e.jsxs(I,{to:`/guide/${b.id}`,className:"group flex min-w-0 items-center justify-end gap-2 rounded-lg border border-border bg-surface px-3 py-2.5 text-right no-underline hover:bg-surface-raised",children:[e.jsxs("span",{className:"min-w-0",children:[e.jsx("span",{className:"block font-mono text-[0.625rem] uppercase tracking-wider text-content-subtle",children:"Next"}),e.jsx("span",{className:"block truncate text-sm font-medium text-content-muted group-hover:text-content",children:b.title})]}),e.jsx("span",{"aria-hidden":!0,className:"text-content-subtle",children:"→"})]}):e.jsx("span",{})]})]}),e.jsx("aside",{className:"hidden xl:block",children:e.jsxs("nav",{"aria-label":"On this page",className:"sticky top-20 border-l border-border pl-4",children:[e.jsx("p",{className:"m-0 mb-2 font-mono text-[0.625rem] uppercase tracking-[0.16em] text-content-subtle",children:"On this page"}),e.jsx("div",{className:"flex flex-col gap-0.5",children:w.map(c=>e.jsx("a",{href:`#${T(l.id,c.id)}`,onClick:g=>j(g,c.id),className:"rounded-md bg-transparent px-2 py-1.5 text-left text-xs leading-snug text-content-subtle hover:bg-surface hover:text-content",children:c.title},c.id))})]})})]})}export{we as ALL_GUIDE_CHAPTERS,P as CHAPTERS,x as FIRST_RUN_STEPS,me as GUIDE_DOCUMENT_ROUTES,L as HELP_CHAPTER,R as REFERENCE_CHAPTERS,ve as default,T as guideHeadingRoute,fe as keepGuideItemVisible,ge as resolveGuideLink};
