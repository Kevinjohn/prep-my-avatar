# Step 3: Configure ComfyUI

ComfyUI is optional. It enables local FLUX.2 Klein image generation and the Test Studio. Skip it if you only want to import photos, use a remote image provider, or export data for another tool.

## Before you begin

Local image generation needs a compatible GPU, a separate ComfyUI installation, and large model downloads. Installing Prep My Avatar does not install ComfyUI automatically.

## Do this

1. On **Step 2 of 5 — Local generation — ComfyUI**, check whether the page says ComfyUI is already running.
2. If it is not installed, follow the **ComfyUI on GitHub** link, install it, and start it. Its usual address is `http://127.0.0.1:8188`.
3. Enter the **ComfyUI install directory** and **ComfyUI API URL** shown by your installation.
4. Select **Save & re-check**. The directory is valid only when it contains ComfyUI's `main.py` file and `models` folder.
5. If you want local Klein generation, accept the model licence, add any required Hugging Face token in Settings, and use the offered model, text-encoder, VAE, and consistency-LoRA downloads.
6. Select **Save & continue →**.

To skip this step, leave the fields unchanged and continue. You can return through **Setup** or **Settings → Local tools**.

## You are finished when

The page reports that ComfyUI is running at the configured URL, or you have deliberately skipped local generation. The wizard then shows the local-vision step.
