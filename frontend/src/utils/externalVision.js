export const EXTERNAL_VISION_PROVIDERS = [
  { id: 'configured', label: 'Local settings' },
  { id: 'chatgpt', label: 'ChatGPT subscription' },
  { id: 'openai', label: 'OpenAI API' },
  { id: 'gemini', label: 'Google Gemini API' },
];

export function externalVisionPayload(provider) {
  if (!['openai', 'chatgpt', 'gemini'].includes(provider)) return {};
  return { provider, allow_external_images: true };
}

export function externalVisionWarning(provider, count) {
  const destination = provider === 'gemini'
    ? 'Google Gemini'
    : provider === 'chatgpt' ? 'ChatGPT subscription' : 'OpenAI';
  const channel = provider === 'chatgpt' ? 'connected ChatGPT account' : `${destination} API`;
  const total = Math.max(0, Number(count) || 0);
  return {
    title: `Send images to ${destination}?`,
    message: `${total} dataset image${total === 1 ? '' : 's'} will leave this machine and be sent through the ${channel} for visual analysis. Provider data handling and retention terms apply.`,
    confirmLabel: `Send to ${destination}`,
  };
}
