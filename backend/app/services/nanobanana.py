"""Nano Banana (Gemini image API) variation generator for the face Dataset Maker.

Sends the reference photo + a variation prompt to the Gemini image model and
returns the generated image bytes. No GPU, no ComfyUI involvement — runs fully
off-device, so dataset generation can happen while local generations run.
SFW only by provider policy (fits the face-dataset use case by design).
"""
from __future__ import annotations
import base64
import logging
import re
import time
from urllib.parse import urlparse

import requests

from .. import config as cfg

logger = logging.getLogger(__name__)

NANOBANANA_MODEL = 'gemini-3-pro-image'
_API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_REPLICATE_API = 'https://api.replicate.com/v1/models/{owner}/{model}/predictions'
_REPLICATE_MODEL_RE = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')


def _api_key():
    return cfg.secret('GEMINI_API_KEY')


def _replicate_key():
    return cfg.secret('REPLICATE_API_TOKEN')


def parse_image_response(data) -> bytes | None:
    """Extract the first inline image from a generateContent response."""
    try:
        for cand in data.get('candidates', []):
            for part in (cand.get('content') or {}).get('parts', []):
                inline = part.get('inlineData') or part.get('inline_data') or {}
                if inline.get('data'):
                    return base64.b64decode(inline['data'])
    except (TypeError, ValueError, KeyError):
        return None
    return None


def _generate_google(refs: list[bytes], prompt: str, model: str | None,
                     aspect_ratio: str) -> bytes | None:
    key = _api_key()
    if not key:
        logger.warning("nanobanana: GEMINI_API_KEY missing in environment")
        return None
    mdl = model or cfg.get('engines.google_image_model') or NANOBANANA_MODEL
    parts = [{"text": prompt}]
    for rb in refs:
        parts.append({"inlineData": {"mimeType": "image/webp",
                                     "data": base64.b64encode(rb).decode('ascii')}})
    payloads = [
        {"contents": [{"parts": parts}],
         "generationConfig": {"responseModalities": ["TEXT", "IMAGE"],
                              "imageConfig": {"aspectRatio": aspect_ratio}}},
        {"contents": [{"parts": parts}],
         "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}},
    ]
    for i, payload in enumerate(payloads):
        try:
            r = requests.post(_API.format(model=mdl),
                              headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                              json=payload, timeout=(10, 180))
        except requests.RequestException as e:
            logger.warning(f"nanobanana: request error: {e}")
            return None
        if r.status_code == 400 and i == 0:
            continue
        if r.status_code != 200:
            logger.warning(f"nanobanana: HTTP {r.status_code}: {r.text[:300]}")
            return None
        try:
            response_data = r.json()
        except ValueError as exc:
            logger.warning("nanobanana: malformed JSON response: %s", exc)
            return None
        img = parse_image_response(response_data)
        if img is None:
            logger.warning("nanobanana: no image in response (safety block or text-only)")
        return img
    return None


def _safe_replicate_output_url(raw) -> str | None:
    if not isinstance(raw, str):
        return None
    parsed = urlparse(raw)
    host = (parsed.hostname or '').lower()
    if parsed.scheme != 'https' or not (
            host == 'replicate.delivery' or host.endswith('.replicate.delivery')):
        return None
    return raw


def _generate_replicate(refs: list[bytes], prompt: str, model: str | None,
                        aspect_ratio: str) -> bytes | None:
    key = _replicate_key()
    if not key:
        logger.warning('nanobanana: REPLICATE_API_TOKEN missing')
        return None
    mdl = model or cfg.get('engines.replicate_image_model') or 'google/nano-banana-pro'
    if not _REPLICATE_MODEL_RE.fullmatch(mdl):
        logger.warning('nanobanana: invalid Replicate model identifier')
        return None
    owner, model_name = mdl.split('/', 1)
    image_input = [
        'data:image/webp;base64,' + base64.b64encode(item).decode('ascii')
        for item in refs
    ]
    headers = {
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json',
        'Prefer': 'wait=60',
        'Cancel-After': '4m',
    }
    try:
        response = requests.post(
            _REPLICATE_API.format(owner=owner, model=model_name),
            headers=headers,
            json={'input': {
                'prompt': prompt, 'image_input': image_input,
                'aspect_ratio': aspect_ratio, 'resolution': '2K',
                'output_format': 'jpg',
                # Identity work must fail visibly if the requested model is at
                # capacity; a silent provider/model substitution is unacceptable.
                'allow_fallback_model': False,
            }},
            timeout=(10, 70),
        )
        response.raise_for_status()
        prediction = response.json()
        prediction_id = prediction.get('id') if isinstance(prediction, dict) else None
        deadline = time.monotonic() + 180
        while isinstance(prediction, dict) and prediction.get('status') not in {
                'succeeded', 'failed', 'canceled'}:
            if not isinstance(prediction_id, str) or not prediction_id.isalnum() \
                    or time.monotonic() >= deadline:
                return None
            time.sleep(1)
            response = requests.get(
                f'https://api.replicate.com/v1/predictions/{prediction_id}',
                headers={'Authorization': f'Bearer {key}'}, timeout=(10, 30),
                allow_redirects=False)
            response.raise_for_status()
            prediction = response.json()
        if not isinstance(prediction, dict) or prediction.get('status') != 'succeeded':
            logger.warning('nanobanana: Replicate prediction failed: %s',
                           prediction.get('error') if isinstance(prediction, dict) else 'bad response')
            return None
        output_url = _safe_replicate_output_url(prediction.get('output'))
        if not output_url:
            logger.warning('nanobanana: Replicate returned an untrusted output URL')
            return None
        output = requests.get(output_url, timeout=(10, 60), allow_redirects=False)
        output.raise_for_status()
        return output.content or None
    except (requests.RequestException, ValueError, TypeError) as exc:
        logger.warning('nanobanana: Replicate request failed: %s', exc)
        return None


def generate_variation(ref_bytes: bytes | list[bytes], prompt: str, model: str | None = None,
                       aspect_ratio: str = '1:1') -> bytes | None:
    """Reference photo(s) + variation prompt -> generated image bytes, or None.

    `ref_bytes` : une image (bytes) ou une LISTE d'images de la même personne
    (multi-références — gemini-3-pro-image accepte jusqu'à 14 images d'entrée et
    s'appuie sur toutes pour la cohérence d'identité). La principale en premier.
    `aspect_ratio` (ex. '1:1' visage, '3:4' buste/corps) évite de letterboxer les
    plans corps. Tries with imageConfig first (Pro models); on a 400 retries once
    with a slim payload for models that don't accept imageConfig."""
    refs = list(ref_bytes)[:14] if isinstance(ref_bytes, (list, tuple)) else [ref_bytes]
    provider = cfg.get('engines.nanobanana_provider') or 'google'
    if provider == 'replicate':
        return _generate_replicate(refs, prompt, model, aspect_ratio)
    return _generate_google(refs, prompt, model, aspect_ratio)
