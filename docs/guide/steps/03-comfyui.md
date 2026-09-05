# Step 3: Configure ComfyUI

ComfyUI is the local alternative to the API/cloud providers on the previous page. Generating missing images requires at least one of those choices. ComfyUI also enables the Test Studio; skip it if you chose a remote provider or only want to import and export photos.

## Before you begin

Local image generation needs a compatible GPU, a separate ComfyUI installation, and large model downloads. Installing Prep My Avatar does not install ComfyUI automatically.

The HTML version of this step records the exact ComfyUI Desktop paths, Klein 9B
filenames, and verification steps used on a working installation.

## Choose one installation method

### Option A — Comfy Desktop (recommended on macOS and Windows)

1. [Download Comfy Desktop](https://www.comfy.org/download), install it, and open it.
2. Create or select an instance. Comfy Desktop owns that instance’s Python environment, GPU setup, and server process.
3. In the instance menu, open **Storage**. Copy its **application directory** into Prep My Avatar’s **ComfyUI install directory** field. Do not enter `/Applications/Comfy Desktop.app` or the shared-model directory.
4. On the dashboard, click the card for the instance you want to run. Opening Comfy Desktop alone does not start its server. On the verified Mac, `open -b com.todesktop.241012ess7yxs0e` opens the dashboard and the instance card is named **ComfyUI-desktop**.
5. Wait for `http://127.0.0.1:8188`, then select **Save & re-check**.

If the selected folder contains `.comfy_environment`, it is Desktop-managed. Always start it through Comfy Desktop rather than invoking its private `main.py`.

### Option B — Git/manual installation

Use this route only if you want to maintain the clone and Python environment yourself:

```bash
git clone https://github.com/comfyanonymous/ComfyUI
cd ComfyUI
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py --listen 127.0.0.1 --port 8188
```

Leave Terminal open while using ComfyUI. On Apple Silicon, the official ComfyUI instructions currently require an MPS-capable PyTorch build and recommend the latest PyTorch nightly; follow the [official Apple Silicon note](https://github.com/comfyanonymous/ComfyUI#apple-mac-silicon) before installing the remaining requirements. Enter the clone’s full path in **ComfyUI install directory**, then select **Save & re-check**.

## How Prep My Avatar identifies the installation type

Prep My Avatar does not decide from the folder name. After you save the ComfyUI directory, it resolves that directory (including a nested `ComfyUI` child in portable layouts) and checks the files inside it:

1. A `.comfy_environment` file identifies an instance managed by **ComfyUI Desktop**.
2. Otherwise, a `main.py` file identifies **ComfyUI from Git / code**.
3. If neither marker is present, the installation type is unknown and the page asks you to correct the configured directory instead of inventing a startup command.

On macOS, Prep My Avatar also looks for a Comfy application in `/Applications` and `~/Applications`. It reads the application’s `Info.plist` to obtain its real name, bundle identifier, and launch command. This application scan helps Prep My Avatar open Comfy Desktop, but it does **not** classify the configured folder: a user can have Comfy Desktop and a separate Git clone installed at the same time. The `.comfy_environment` marker is what connects a particular folder to Desktop management.

This is a filesystem heuristic, not a permanent guarantee from ComfyUI. If a future ComfyUI Desktop release stops creating `.comfy_environment`, a Desktop instance that still contains `main.py` may be labelled as Git/code until Prep My Avatar’s detection is updated. The configured path and detected type contain no username-specific or machine-specific hardcoding; every installation is checked locally in the same way.

## Do this

1. On **Step 2 of 5 — Local image provider — ComfyUI**, check whether the page says ComfyUI is already running.
2. Start it using the matching method above: click the instance card on the Comfy Desktop dashboard, or run `python main.py --listen 127.0.0.1 --port 8188` from an activated manual-install environment.
3. Enter the **ComfyUI install directory** and **ComfyUI API URL** shown by your installation.
4. Select **Save & re-check**. A classic ComfyUI directory contains `models` and `main.py`; ComfyUI Desktop uses the supported `models` and `custom_nodes` layout instead.
5. If you want local Klein generation, accept the model licence, add any required Hugging Face token in Settings, and use the offered model, text-encoder, VAE, and consistency-LoRA downloads.
6. Select **Save & continue →**.

The **Start this session** detail checks for `.comfy_environment`. For a Desktop-managed installation, it gives the detected Desktop application command and names the instance to select; it does not pretend the folder is a standalone clone. For an ordinary clone, it displays the verified folder command with Copy buttons. If neither launch route can be verified, the page says so instead of inventing a command. Returning from that detail takes you back to **Start this session**, not to Setup.

To skip this step, leave the fields unchanged and continue. You can return through **Setup** or **Settings → Local tools**.

## You are finished when

The page reports that ComfyUI is running at the configured URL, or you have deliberately skipped local generation. The wizard then shows the local-vision step.
