export function formatDiagnostic(d) {
  const yn = (value) => (value ? 'yes' : 'no');
  const capabilities = d.capabilities || {};
  const engines = capabilities.engines || {};
  const config = d.config || {};
  const lines = [
    `Prep My Avatar diagnostic — v${d.app_version}${d.git_sha ? ` (${d.git_sha})` : ''}`,
    `OS: ${d.os} · Python ${d.python}`,
    `Engines: nanobanana=${yn(engines.nanobanana)} chatgpt=${yn(engines.chatgpt)} klein=${yn(engines.klein)} (default: ${config.default_engine})`,
    `ComfyUI: reachable=${yn(capabilities.comfyui_reachable)} klein_model=${yn(capabilities.klein_model)} · Ollama: reachable=${yn(capabilities.ollama_reachable)} vision_model=${yn(capabilities.vision_model_ready)}`,
    `ai-toolkit: ${yn(capabilities.aitoolkit_valid)} · face scoring: ${yn(capabilities.face_scoring)} · masks: ${yn(capabilities.masks)} · cloud: ${yn(capabilities.cloud_training)}`,
    `Captioning: ${config.captioning_backend} · default family: ${config.training_default_family} · LAN: ${yn(config.lan_enabled)}`,
    `Keys set: ${Object.entries(d.secrets_present || {}).filter(([, value]) => value).map(([key]) => key).join(', ') || 'none'}`,
    '--- last log lines ---',
    ...(d.log_tail || []).slice(-40),
  ];
  const longestFence = Math.max(2, ...lines.map((line) => {
    const runs = String(line).match(/`+/g);
    return runs ? Math.max(...runs.map((run) => run.length)) : 0;
  }));
  const fence = '`'.repeat(longestFence + 1);
  return [fence, ...lines, fence].join('\n');
}
