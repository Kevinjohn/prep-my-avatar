# Step 4: Configure local vision

Local vision can classify your photos, map coverage, and write first-draft captions without sending those photos to a remote captioning service. You may use **Ollama**, **LM Studio**, or **llama.cpp**.

## Before you begin

Each choice needs a running local server and a vision-capable, or “multimodal,” model. A text-only model cannot inspect images.

The local-vision capability is required to advance once you enter Setup. If you do not want to configure it now, use the wizard's global **Skip setup — I'll do it later** action. That exits Setup and opens **Datasets**; you can configure local vision later from **Setup** or **Settings**.

## Do this

1. On **Step 3 of 5 — Local vision**, open **Local vision backend**.
2. Choose one backend:
   - **Ollama:** install and start Ollama, keep the default URL unless you changed it, then pull the model offered by the wizard.
   - **LM Studio:** start its local server, load a vision model, and use its OpenAI-compatible URL, normally `http://127.0.0.1:1234/v1`.
   - **llama.cpp:** start `llama-server` with a vision model and projector, then use its OpenAI-compatible URL, normally `http://127.0.0.1:8080/v1`.
3. Enter the exact loaded model identifier in the **vision model** field.
4. Select **Save & re-check**.
5. Correct the URL or loaded model if the check fails, then re-check.
6. Select **Save & continue →**.

If you want to work without automatic analysis and captioning, select **Skip setup — I'll do it later** instead of trying to continue from this screen. Manual photo classification and caption editing remain available.

## You are finished when

The page says the selected backend is running and its vision model is loaded, then the wizard shows **Quality tools — ML extras**. If you used the global Setup skip, **Datasets** opens instead.
