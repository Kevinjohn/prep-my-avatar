# Step 20: Test the LoRA in Studio

Studio compares checkpoints and strengths with the same prompts and seeds. This separates the effect of the LoRA from random changes between generated images. This step is optional; if you have no compatible checkpoint or do not use Studio, continue to Step 21.

## Before you begin

Studio needs a working ComfyUI setup, compatible base models and nodes, and at least one checkpoint. If Studio cannot run, return to Setup and configure ComfyUI, or skip this optional page and continue to Step 21.

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
10. Open any result image you need to keep and select **Download image** in its preview.

## You are finished when

The dataset has starred **best settings** backed by more than one useful prompt. Record the winning checkpoint filename and strength. Use **Run folder** or **LoRA folder** under **Checkpoints & LoRAs** to locate and copy the checkpoint for the image-generation workflow where you will use it, then continue to Step 21.
