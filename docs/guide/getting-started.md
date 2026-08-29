# Getting started

> Prefer a visual walkthrough? Launch the app and choose **Guide → Getting started**, or open `docs/guide/getting-started.html` from your local copy of the repository. This Markdown file is the plain-text reference.

## Open the app

Prep My Avatar is a local web app. It runs on your computer and you use it in a
web browser; opening this guide does not start the app.

### Windows

Clone or download the repository, then double-click **`start.bat`**.

### macOS or Linux

Open a terminal in the repository folder and run these commands for the first
launch:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
python backend/source_launcher.py --install --root . --data-dir data
python data/source-launcher.py --root . --data-dir data
```

For later launches, run only:

```bash
source .venv/bin/activate
python data/source-launcher.py --root . --data-dir data
```

Then open **<http://127.0.0.1:5050/>**. Keep the terminal window open while you
use the app; press `Ctrl+C` there to stop it.

The first launch opens the Setup wizard. You can skip optional integrations and
start by importing and reviewing your photos.

## The problem this solves

You need recognisable photos or videos of yourself repeatedly—for a website, social post, presentation, campaign, thumbnail, or story. Another photoshoot every time is slow, and starting from scratch with an image tool can produce a different-looking person on every attempt. The goal is not to own an avatar. The goal is to make useful new material featuring your likeness without rebuilding that likeness for every image, video, or service.

This is useful for creators, founders, educators, performers, campaigners, and anyone else who regularly needs consistent images of themselves.

The problem is repetition and inconsistency: useful photographs are scattered, similar selfies provide limited evidence, and each image tool can create a different-looking person. Prep My Avatar helps you prepare reliable evidence once. Start with five strong photos, review them, and add genuinely different views only when your intended result needs them. You can then use those photos directly with a capable model or train a compatible LoRA when you need repeated consistency and more control.

“Digital avatar” is only shorthand for several possible solutions. Prep My Avatar can prepare reference images, export a portable image-and-caption training pack, or train a family-specific Character LoRA. A provider-owned avatar—such as Gemini’s face-and-voice personal avatar—is created and stored by that provider, not by this app.

Choose where you want to reuse your likeness before choosing tools:

| You want | The actual output | Where it goes |
| --- | --- | --- |
| New still images of yourself | Reference photos and finished image files | A service that accepts image references, including the supported in-app generation engines |
| A reusable image-model identity | A Character LoRA `.safetensors` file tied to one model family | A compatible Z-Image, SDXL, Krea 2, FLUX.1, or FLUX.2 Klein workflow |
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

For a first run with photos of yourself, choose **Character**. Use a distinctive trigger such as `zchar_alex`, not a common word such as `alex` or `person`.

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

The **Open the app** section near the top is the shortest route. The repository README's
[Installation and launch](https://github.com/Kevinjohn/prep-my-avatar#installation-and-launch)
section is the canonical launch reference; the following sections add platform
notes, environment configuration, and Docker's API-only route.

### Windows: use the bundled launcher

Clone or download the repository, then double-click **`start.bat`**. It creates the local Python environment, installs the core dependencies, starts the app, and opens it at:

```text
http://127.0.0.1:5050/
```

The launcher prefers Python 3.11 or 3.12. If neither is installed, it can download a self-contained Python 3.12 on an online Windows machine. The app's core features can run without the optional machine-learning extras.

### macOS or Linux: run the launcher manually

Use Python 3.11 or 3.12 if you want the optional face scoring, person masks, or watermark tools. The core application requires Python 3.10 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
python backend/source_launcher.py --install --root . --data-dir data
python data/source-launcher.py --root . --data-dir data
```

Then open `http://127.0.0.1:5050/` in your browser.

On Windows, the equivalent manual commands use `.venv\Scripts\activate` and `python` rather than `python3`.

### Configure keys and defaults with `.env`

Copy `.env.example` to `.env` for a source or Docker install. The portable
launcher creates `data/.env` from the same template on first launch. You can put
provider keys there and preselect the enabled/default generation engines, image
models, OpenAI quality, Ollama model, and local service URLs.

Effective settings resolve in this order:

1. a value explicitly saved in `config.json` or the Settings screen;
2. a process environment variable supplied by the launcher or operator;
3. the matching value in `.env`;
4. the built-in safe default.

Settings shows the winning source for configurable provider/model fields. Use
**Follow environment/default** to remove a `config.json` override, or **Pin in
Settings** to preserve the current effective value in `config.json`. API keys
remain write-only and are never returned to the browser.

### Docker: API-only mode

Docker runs the core app and does not include ComfyUI or ai-toolkit. Copy
`.env.example` to `.env`, add a long random access token, and start the container.
Docker reads this root file as operator-managed startup environment; keys saved
through Settings are written separately to `data-docker/.env`:

Put this in `.env`:

```dotenv
LDS_ACCESS_TOKEN=replace-with-a-long-random-value
```

Then run:

```bash
docker compose up --build
```

Open `http://127.0.0.1:5050/remote-login` and enter the token from `.env`.

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

- the ComfyUI API, normally `http://127.0.0.1:8188`; and
- the ComfyUI folder containing `main.py` and `models/`.

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
