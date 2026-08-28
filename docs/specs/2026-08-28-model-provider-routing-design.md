# Model and provider routing

- **Status:** Proposed for later implementation
- **Date:** 2026-08-28

## Goal

Separate the model a user wants from the service that runs it. This allows local
photo analysis through either Ollama or LM Studio, and allows the same remote
image model to be reached through more than one provider.

## Proposed user model

```text
Local vision backend:
  Ollama | LM Studio

Generation model:
  Nano Banana Pro | ChatGPT Image | another supported image model

Remote provider:
  Google direct | OpenAI direct | Replicate | OpenRouter
```

The generation UI should select a model first, then show compatible providers.
Provider availability, capabilities, pricing and credentials remain
provider-specific.

## Initial scope

- Add LM Studio as an alternative to Ollama for local coverage analysis,
  captioning and other vision tasks. Use LM Studio's OpenAI-compatible image
  input API and require a loaded vision-capable model.
- Add Replicate and OpenRouter as remote image-generation providers.
- Support Nano Banana through Google direct, Replicate and OpenRouter where each
  provider advertises the required reference-image capability.
- Preserve the existing bounded anchor pack and make it clear which remote
  provider receives those images.
- Keep credentials, health checks, errors, costs and provenance separate for
  each provider.

## Constraints and open questions

- Provider capability and model availability can change, so compatibility and
  pricing should be discovered or configured rather than assumed from a shared
  model name.
- Reference-image limits and request/response formats differ by provider.
- Replicate's Nano Banana Pro currently accepts up to 14 reference images, which
  matches the existing anchor-pack limit.
- Decide later whether the first implementation exposes a curated model list or
  supports arbitrary provider model identifiers.
- Define fallback behavior explicitly; never send images to a second provider
  without the user's prior selection and privacy consent.

## Relevant APIs

- [LM Studio OpenAI-compatible API](https://lmstudio.ai/docs/developer/openai-compat)
- [Replicate Nano Banana Pro API](https://replicate.com/google/nano-banana-pro/api)
- [OpenRouter image generation](https://openrouter.ai/docs/guides/overview/multimodal/image-generation)
