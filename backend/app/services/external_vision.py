"""Small, explicit adapters for supported remote multimodal APIs.

Callers own the user-consent boundary. This module validates the provider,
credential, payload size, and response shape, and never logs image bytes or keys.
"""

from __future__ import annotations

import base64
import json
import uuid

import requests

from .. import config as cfg
from ..domain_errors import DomainConflictError, DomainValidationError

EXTERNAL_PROVIDERS = ("openai", "chatgpt", "gemini")
MAX_IMAGE_BYTES = 20 * 1024 * 1024
CHATGPT_RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"
DEFAULT_MODELS = {
    "openai": "gpt-5.4-mini",
    "chatgpt": "gpt-5.4-mini",
    "gemini": "gemini-2.5-flash",
}
PROVIDER_LABELS = {
    "openai": "OpenAI",
    "chatgpt": "ChatGPT subscription",
    "gemini": "Google Gemini",
}


class ExternalVisionError(DomainConflictError):
    """A configured remote vision request could not be completed."""

    error_code = "external_vision_error"


def _clean_inputs(image_bytes, prompt, provider, mime_type):
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider not in EXTERNAL_PROVIDERS:
        raise DomainValidationError(
            f"Unsupported external vision provider: {normalized_provider or 'blank'}")
    if not isinstance(image_bytes, bytes) or not image_bytes:
        raise DomainValidationError("An image is required for external vision")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise DomainValidationError("Image exceeds the 20 MB external vision limit")
    clean_prompt = str(prompt or "").strip()
    if not clean_prompt:
        raise DomainValidationError("A vision prompt is required")
    clean_mime = str(mime_type or "").strip().lower()
    if clean_mime not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
        raise DomainValidationError("Unsupported image type for external vision")
    return normalized_provider, clean_prompt, clean_mime


def _openai_text(payload):
    for item in payload.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("type") == "output_text":
                text = str(content.get("text") or "").strip()
                if text:
                    return text
    return str(payload.get("output_text") or "").strip()


def _gemini_text(payload):
    direct = str(payload.get("output_text") or "").strip()
    if direct:
        return direct
    for step in payload.get("steps", []):
        if not isinstance(step, dict):
            continue
        output = step.get("model_output") or step.get("output") or {}
        if isinstance(output, str) and output.strip():
            return output.strip()
        for content in output.get("content", []) if isinstance(output, dict) else []:
            if isinstance(content, dict) and content.get("type") in {"text", "output_text"}:
                text = str(content.get("text") or "").strip()
                if text:
                    return text
    return ""


def _chatgpt_stream_text(raw_text):
    deltas = []
    completed = ""
    for line in str(raw_text or "").splitlines():
        if not line.startswith("data:"):
            continue
        try:
            event = json.loads(line[5:].strip())
        except (TypeError, ValueError):
            continue
        if event.get("type") == "response.output_text.delta":
            deltas.append(str(event.get("delta") or ""))
        elif event.get("type") == "response.completed":
            completed = _openai_text(event.get("response") or {})
    return "".join(deltas).strip() or completed


def _describe_via_chatgpt_subscription(encoded, prompt, mime_type, model, timeout):
    from . import chatgpt_oauth

    body = {
        "model": model,
        "input": [{"role": "user", "content": [
            {"type": "input_image",
             "image_url": f"data:{mime_type};base64,{encoded}",
             "detail": "high"},
            {"type": "input_text", "text": prompt},
        ]}],
        "store": False,
        "stream": True,
    }
    for attempt in (0, 1):
        token = chatgpt_oauth.access_token(force_refresh=bool(attempt))
        if not token:
            raise ExternalVisionError(
                "ChatGPT subscription is not connected; reconnect it in Settings")
        response = requests.post(
            CHATGPT_RESPONSES_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "chatgpt-account-id": chatgpt_oauth.account_id() or "",
                "OpenAI-Beta": "responses=experimental",
                "originator": "codex_cli_rs",
                "session_id": str(uuid.uuid4()),
            },
            json=body,
            timeout=timeout,
        )
        if response.status_code == 401 and attempt == 0:
            continue
        if response.status_code == 401:
            raise ExternalVisionError(
                "ChatGPT subscription connection expired; reconnect it in Settings")
        if response.status_code == 429:
            raise ExternalVisionError(
                "ChatGPT subscription usage limit reached; wait for the plan limit to reset")
        if response.status_code != 200:
            raise ExternalVisionError(
                "ChatGPT subscription rejected the vision request; check the connection and selected model")
        content_type = str(response.headers.get("content-type") or "")
        head = str(response.text or "")[:64].lstrip()
        if "text/event-stream" in content_type or head.startswith(("data:", "event:")):
            return _chatgpt_stream_text(response.text)
        return _openai_text(response.json())
    return ""


def describe_image_external(image_bytes, prompt, *, provider, mime_type,
                            model=None, timeout=(10, 120)):
    """Send one image to the selected provider and return bounded text."""
    provider, prompt, mime_type = _clean_inputs(
        image_bytes, prompt, provider, mime_type)
    config_model = (cfg.get("engines.chatgpt_subscription_model")
                    if provider == "chatgpt"
                    else cfg.get(f"external_vision.{provider}_model"))
    model = str(model or config_model or DEFAULT_MODELS[provider]).strip()
    encoded = base64.b64encode(image_bytes).decode("ascii")
    try:
        if provider == "chatgpt":
            text = _describe_via_chatgpt_subscription(
                encoded, prompt, mime_type, model, timeout)
        else:
            secret_name = "OPENAI_API_KEY" if provider == "openai" else "GEMINI_API_KEY"
            api_key = cfg.secret(secret_name)
            if not api_key:
                raise ExternalVisionError(
                    f"{PROVIDER_LABELS[provider]} API key is not configured in Settings")
        if provider == "openai":
            response = requests.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {api_key}",
                         "Content-Type": "application/json"},
                json={
                    "model": model,
                    "store": False,
                    "max_output_tokens": 2000,
                    "input": [{"role": "user", "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image",
                         "image_url": f"data:{mime_type};base64,{encoded}",
                         "detail": "high"},
                    ]}],
                },
                timeout=timeout,
            )
            extractor = _openai_text
        elif provider == "gemini":
            response = requests.post(
                "https://generativelanguage.googleapis.com/v1beta/interactions",
                headers={"x-goog-api-key": api_key,
                         "Content-Type": "application/json"},
                json={
                    "model": model,
                    "input": [
                        {"type": "image", "mime_type": mime_type, "data": encoded},
                        {"type": "text", "text": prompt},
                    ],
                },
                timeout=timeout,
            )
            extractor = _gemini_text
        if provider != "chatgpt":
            response.raise_for_status()
            text = extractor(response.json())
    except requests.HTTPError as exc:
        status = getattr(exc.response, "status_code", None)
        label = PROVIDER_LABELS[provider]
        try:
            provider_error = (exc.response.json() or {}).get("error") or {}
            error_code = str(provider_error.get("code") or "")
        except (AttributeError, TypeError, ValueError):
            error_code = ""
        quota_details = {
            "credit_balance_exhausted": (
                "API credit balance is exhausted; add credits in the provider billing settings"),
            "organization_usage_limit_exceeded": (
                "organization usage limit is exhausted; review the organization limits"),
            "organization_spend_limit_exceeded": (
                "organization spend limit is exhausted; review the organization spend controls"),
            "project_spend_limit_exceeded": (
                "project spend limit is exhausted; review that project's spend controls"),
        }
        if error_code in quota_details:
            detail = quota_details[error_code]
        elif status in (401, 403):
            detail = "rejected the API key or model access; check Secrets and the configured vision model"
        elif status == 404:
            detail = "could not find the configured vision model or endpoint; check the model in Settings"
        elif status == 429:
            detail = "rejected the request because of a rate limit or API quota; wait, or check provider billing and limits"
        elif isinstance(status, int) and status >= 500:
            detail = "is temporarily unavailable; retry later"
        else:
            detail = "rejected the request; check the API key, model, and provider status"
        raise ExternalVisionError(f"{label} {detail}") from exc
    except ExternalVisionError:
        raise
    except (requests.RequestException, ValueError, TypeError) as exc:
        raise ExternalVisionError(
            f"{PROVIDER_LABELS[provider]} vision request could not connect or returned an invalid response") from exc
    if not text:
        raise ExternalVisionError(f"{PROVIDER_LABELS[provider]} returned no usable vision text")
    return text[:20_000]
