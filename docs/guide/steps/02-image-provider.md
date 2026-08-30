# Step 2: Choose an image provider

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
