"""Shared Ollama vision captioning helper.

Single responsibility: run one robust vision pass on an image via Ollama and
return the caption text. Ordinary best-effort calls return "" on failure;
caption batches that request local auto-start receive a clear exception if the
server still cannot caption. Lifted from the parent project's seedance_routes extraction so both
the classify/caption passes of the face-dataset service can reuse it without
duplicating the Qwen3-VL quirks.
"""
from __future__ import annotations

import base64
import logging

import requests

from .. import config as cfg

logger = logging.getLogger(__name__)

_OPENAI_COMPATIBLE_PROVIDERS = {
    'lmstudio': 'LM Studio',
    'llamacpp': 'llama.cpp',
}


def _local_vision_backend() -> str:
    return cfg.get('local_vision.backend') or 'ollama'


def _openai_compatible_settings(provider: str) -> tuple[str, str]:
    url = (cfg.get(f'{provider}.url') or '').rstrip('/')
    model = cfg.get(f'{provider}.vision_model') or ''
    if not url or not model:
        raise RuntimeError(
            f'{_OPENAI_COMPATIBLE_PROVIDERS[provider]} URL and vision model must be configured')
    return url, model


def _describe_openai_compatible(image_bytes: bytes, prompt: str, *,
                                provider: str, model: str | None,
                                num_predict: int, prefer_json: bool,
                                fmt: str | None, auto_start_local: bool,
                                timeout) -> str:
    """Run a vision pass through LM Studio or llama.cpp's OpenAI-compatible API."""
    label = _OPENAI_COMPATIBLE_PROVIDERS[provider]
    try:
        url, configured_model = _openai_compatible_settings(provider)
        encoded = base64.b64encode(image_bytes).decode('ascii')
        payload = {
            'model': model or configured_model,
            'messages': [{
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': prompt},
                    {'type': 'image_url', 'image_url': {
                        'url': f'data:image/webp;base64,{encoded}',
                    }},
                ],
            }],
            'temperature': 0.3,
            'max_tokens': int(num_predict),
            'stream': False,
        }
        if prefer_json or fmt:
            payload['response_format'] = {'type': 'json_object'}
        response = requests.post(
            f'{url}/chat/completions', json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        choices = data.get('choices') if isinstance(data, dict) else None
        content = ((choices or [{}])[0].get('message') or {}).get('content')
        if not isinstance(content, str):
            raise ValueError('response did not contain assistant text')
        return content.strip()
    except Exception as exc:
        if auto_start_local:
            raise RuntimeError(
                f'{label} is unavailable or its configured vision model is not loaded') from exc
        logger.warning('vision_local: %s describe skipped: %s', label, exc)
        return ''


def _ollama_url() -> str:
    # Total accessor: cfg.get() can return None (missing/corrupted config
    # section) and callers rstrip('/') the result unconditionally -- this
    # must never hand back None, or the never-raise contract below breaks.
    return cfg.get('ollama.url') or 'http://127.0.0.1:11434'


def get_vision_model() -> str:
    """Resolve the Ollama vision model: env ``VISION_OLLAMA_MODEL`` > config
    ``ollama.vision_model`` (defaults to 'huihui_ai/qwen3-vl-abliterated:8b-instruct', see
    config.DEFAULTS — the ABLITERATED/uncensored Qwen3-VL, needed because the vanilla
    'qwen3-vl:8b' refuses to describe the NSFW concept datasets this app captions).
    CRITICAL: use the '-instruct' tag, NOT plain ':8b' (which resolves to the THINKING
    variant). The Thinking model reasons out loud in the response on caption/omission tasks
    ("So the shot type is... Wait, is that the shared element?") - benchmarked 2/8 usable vs
    8/8 for -instruct, and ~8x slower (13s vs 1.6s/image). The 30b-a3b-instruct ties -instruct
    on quality at 3x the VRAM, so -instruct is the default; upgrade via config without code."""
    return cfg.get('ollama.vision_model') or 'huihui_ai/qwen3-vl-abliterated:8b-instruct'


def describe_image_ollama(image_bytes: bytes, prompt: str, *,
                          ollama_url: str | None = None,
                          model: str | None = None,
                          num_predict: int = 800,
                          num_ctx: int = 8192,
                          repeat_penalty: float = 1.1,
                          prefer_json: bool = False,
                          fmt: str | None = None,
                          keep_alive: str | int = 0,
                          auto_start_local: bool = False,
                          timeout: tuple[float, float] | float = (10, 120)) -> str:
    """Describe an image via Ollama vision. Returns the caption text, or "" on
    failure for ordinary best-effort calls. With ``auto_start_local=True``, a
    stopped local server is started once and a persistent failure raises a
    user-facing RuntimeError.

    `timeout` is a (connect, read) tuple by default: fail fast (10s) when Ollama
    is unreachable so a caller never hangs, but allow a long read (120s) for a
    cold model load + inference. Pass a single float to use it for both phases.

    Model variant matters: the default is now the `-instruct` tag (NON-thinking) — it
    answers directly, no reasoning trace, so a modest `num_predict` suffices. The
    `-thinking` / plain `:8b` variant instead ALWAYS emits a `thinking` trace (~900-1400
    tokens) that can't be skipped (think:false / `/no_think` are ignored by that
    checkpoint); with it, `num_predict` must be large enough to cover the thinking AND the
    answer (>=5000) or the response comes back empty with `done_reason=length`. We still
    fall back to the tail of `thinking` when `response` is empty (harmless with instruct —
    that field is empty — and correct for the thinking variant). `num_ctx` defaults to 8192
    so a long answer (plus any thinking trace) fits in context.

    `keep_alive` (défaut 0) : 0 décharge le modèle après CET appel (VRAM-safe,
    bon pour les appels isolés) ; un batch (caption/classify de N images) doit
    passer une durée (ex. '5m') pour garder le modèle chaud entre les images, PUIS
    appeler unload_vision_model() en fin de batch pour rendre la VRAM à ComfyUI.
    """
    provider = _local_vision_backend()
    if provider in _OPENAI_COMPATIBLE_PROVIDERS:
        return _describe_openai_compatible(
            image_bytes, prompt, provider=provider, model=model,
            num_predict=num_predict, prefer_json=prefer_json, fmt=fmt,
            auto_start_local=auto_start_local, timeout=timeout)
    try:
        url = (ollama_url or _ollama_url()).rstrip('/')
        b64 = base64.b64encode(image_bytes).decode('ascii')
        payload = {
            'model': model or get_vision_model(),
            'prompt': prompt,
            'images': [b64],
            'stream': False,
            'options': {'temperature': 0.3, 'num_ctx': int(num_ctx),
                        'num_predict': int(num_predict),
                        'repeat_penalty': float(repeat_penalty)},
            'keep_alive': keep_alive,
        }
        # `format='json'` constrains the response to valid JSON (Ollama grammar) —
        # stops the abliterated model from rambling prose instead of the object.
        if fmt:
            payload['format'] = fmt
        resp = requests.post(f'{url}/api/generate', json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        caption = (data.get('response') or '').strip()
        thinking = (data.get('thinking') or '').strip()
        # JSON callers: the structured object may land in EITHER `response` or
        # `thinking` (this checkpoint is non-deterministic about it). Return the
        # FULL field that contains an object so the caller's JSON extractor can
        # pull it out — the last-paragraph heuristic below would truncate it.
        if prefer_json:
            for cand in (caption, thinking):
                if '{' in cand:
                    return cand
            return caption or thinking
        if caption:
            return caption
        if thinking:
            done_reason = data.get('done_reason')
            logger.info('vision_ollama: response empty, falling back to thinking (done_reason=%s)',
                        done_reason)
            parts = [p.strip() for p in thinking.split('\n\n') if p.strip()]
            if not parts:
                return thinking
            # Graceful fallback: when the answer was truncated (done_reason='length')
            # the model never emitted a clean `response`, and the usable description is
            # the tail of a LONG thinking trace. Returning only the final paragraph
            # there collapses the scene to one sentence, so when the trace is genuinely
            # long we keep the last few paragraphs instead. A short trace's last
            # paragraph is already the whole answer, so we leave that case unchanged.
            if done_reason == 'length' and len(parts) > 3:
                return '\n\n'.join(parts[-3:])
            return parts[-1]
        return ''
    except Exception as e:
        if auto_start_local:
            from . import ollama_control
            ready = ollama_control.ensure_captioning_ready()
            if not ready.get('ok'):
                raise RuntimeError(ready.get('error') or 'Ollama is unavailable') from e
            retried = describe_image_ollama(
                image_bytes, prompt, ollama_url=ollama_url, model=model,
                num_predict=num_predict, num_ctx=num_ctx,
                repeat_penalty=repeat_penalty, prefer_json=prefer_json, fmt=fmt,
                keep_alive=keep_alive, auto_start_local=False, timeout=timeout)
            if not retried:
                raise RuntimeError(
                    'Ollama did not return a caption after restart — check the configured '
                    'vision model and the application log.') from e
            return retried
        logger.warning('vision_ollama: describe skipped: %s', e)
        return ''


def unload_vision_model(*, ollama_url: str | None = None, model: str | None = None) -> bool:
    """Décharge le modèle vision d'Ollama (libère la VRAM). À appeler à la FIN d'un
    batch caption/classify (où les appels ont gardé le modèle chaud via keep_alive)
    AVANT que ComfyUI reprenne le GPU, sinon le modèle resterait chargé et ComfyUI
    pourrait manquer de VRAM. Retente une fois car un unload raté = ~5 min résident
    (keep_alive). Retourne True si l'appel a réussi."""
    if _local_vision_backend() != 'ollama':
        # The OpenAI-compatible contract has no portable unload operation.
        return True
    try:
        url = (ollama_url or _ollama_url()).rstrip('/')
        payload = {'model': model or get_vision_model(), 'keep_alive': 0}
    except Exception as e:
        logger.warning('vision_ollama: unload url/model resolution échouée : %s', e)
        return False
    for attempt in (1, 2):
        try:
            response = requests.post(
                f'{url}/api/generate', json=payload, timeout=(10, 30))
            response.raise_for_status()
            return True
        except Exception as e:
            logger.warning('vision_ollama: unload attempt %d échoué : %s', attempt, e)
    return False
