"""Remote multimodal provider request and response contracts."""

import base64

import pytest


class _Response:
    def __init__(self, payload, status=200, text=None, headers=None):
        self.payload = payload
        self.status_code = status
        self.text = text if text is not None else "provider error"
        self.headers = headers or {}

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(response=self)


def test_openai_uses_responses_image_input(app, monkeypatch):
    from app.services import external_vision

    monkeypatch.setattr(external_vision.cfg, "secret", lambda name: "secret")
    seen = {}

    def post(url, **kwargs):
        seen.update(url=url, **kwargs)
        return _Response({"output": [{"type": "message", "content": [
            {"type": "output_text", "text": "a concise caption"}
        ]}]})

    monkeypatch.setattr(external_vision.requests, "post", post)
    result = external_vision.describe_image_external(
        b"\x89PNG\r\n\x1a\nnot-a-real-image", "Describe it", provider="openai",
        mime_type="image/png", model="gpt-test",
    )

    assert result == "a concise caption"
    assert seen["url"] == "https://api.openai.com/v1/responses"
    assert seen["json"]["model"] == "gpt-test"
    assert seen["json"]["store"] is False
    content = seen["json"]["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "Describe it"}
    assert content[1]["image_url"].startswith("data:image/png;base64,")


def test_gemini_uses_interactions_multimodal_input(app, monkeypatch):
    from app.services import external_vision

    monkeypatch.setattr(external_vision.cfg, "secret", lambda name: "secret")
    seen = {}

    def post(url, **kwargs):
        seen.update(url=url, **kwargs)
        return _Response({"output_text": "structured answer"})

    monkeypatch.setattr(external_vision.requests, "post", post)
    result = external_vision.describe_image_external(
        b"jpeg-data", "Classify it", provider="gemini",
        mime_type="image/jpeg", model="gemini-test",
    )

    assert result == "structured answer"
    assert seen["url"] == "https://generativelanguage.googleapis.com/v1beta/interactions"
    assert seen["headers"]["x-goog-api-key"] == "secret"
    assert seen["json"]["model"] == "gemini-test"
    assert seen["json"]["input"] == [
        {"type": "image", "mime_type": "image/jpeg",
         "data": base64.b64encode(b"jpeg-data").decode("ascii")},
        {"type": "text", "text": "Classify it"},
    ]


def test_chatgpt_subscription_uses_connected_oauth_and_streamed_text(app, monkeypatch):
    from app.services import chatgpt_oauth, external_vision

    monkeypatch.setattr(chatgpt_oauth, "access_token", lambda force_refresh=False: "oauth-token")
    monkeypatch.setattr(chatgpt_oauth, "account_id", lambda: "account-id")
    seen = {}

    def post(url, **kwargs):
        seen.update(url=url, **kwargs)
        stream = '\n'.join([
            'data: {"type":"response.output_text.delta","delta":"a clear "}',
            'data: {"type":"response.output_text.delta","delta":"caption"}',
            'data: {"type":"response.completed","response":{"output":[]}}',
        ])
        return _Response({}, text=stream, headers={"content-type": "text/event-stream"})

    monkeypatch.setattr(external_vision.requests, "post", post)
    result = external_vision.describe_image_external(
        b"jpeg-data", "Describe it", provider="chatgpt",
        mime_type="image/jpeg", model="gpt-test",
    )

    assert result == "a clear caption"
    assert seen["url"] == "https://chatgpt.com/backend-api/codex/responses"
    assert seen["headers"]["Authorization"] == "Bearer oauth-token"
    assert seen["headers"]["chatgpt-account-id"] == "account-id"
    assert seen["json"]["store"] is False
    assert seen["json"]["stream"] is True
    assert seen["json"]["input"][0]["content"][0]["type"] == "input_image"


@pytest.mark.parametrize("provider", ["openai", "gemini"])
def test_external_provider_requires_configured_key(app, monkeypatch, provider):
    from app.services import external_vision

    monkeypatch.setattr(external_vision.cfg, "secret", lambda name: None)
    with pytest.raises(external_vision.ExternalVisionError, match="API key"):
        external_vision.describe_image_external(
            b"pixels", "Describe", provider=provider, mime_type="image/png")


def test_external_provider_rejects_unknown_provider(app):
    from app.domain_errors import DomainValidationError
    from app.services.external_vision import describe_image_external

    with pytest.raises(DomainValidationError, match="Unsupported"):
        describe_image_external(b"pixels", "Describe", provider="mystery",
                                mime_type="image/png")


def test_openai_quota_error_is_actionable_without_exposing_provider_body(app, monkeypatch):
    from app.services import external_vision

    monkeypatch.setattr(external_vision.cfg, "secret", lambda name: "secret")
    monkeypatch.setattr(
        external_vision.requests, "post",
        lambda *args, **kwargs: _Response({"error": {"message": "sensitive detail"}}, 429),
    )

    with pytest.raises(external_vision.ExternalVisionError,
                       match="rate limit or API quota") as error:
        external_vision.describe_image_external(
            b"pixels", "Describe", provider="openai", mime_type="image/png")

    assert "sensitive detail" not in str(error.value)


def test_openai_exhausted_credit_code_names_the_actual_fix(app, monkeypatch):
    from app.services import external_vision

    monkeypatch.setattr(external_vision.cfg, "secret", lambda name: "secret")
    monkeypatch.setattr(
        external_vision.requests, "post",
        lambda *args, **kwargs: _Response({"error": {
            "type": "insufficient_quota",
            "code": "credit_balance_exhausted",
            "message": "internal provider wording",
        }}, 429),
    )

    with pytest.raises(external_vision.ExternalVisionError,
                       match="API credit balance is exhausted") as error:
        external_vision.describe_image_external(
            b"pixels", "Describe", provider="openai", mime_type="image/png")

    assert "internal provider wording" not in str(error.value)


@pytest.mark.parametrize("path", ["classify", "caption"])
@pytest.mark.parametrize("provider", ["openai", "chatgpt", "gemini"])
def test_remote_dataset_action_requires_per_request_acknowledgement(
        client, app, path, provider):
    from app.config import LOCAL_USER
    from app.services import face_dataset_service as service

    with app.app_context():
        dataset_id = service.create_dataset(LOCAL_USER, "Remote", "remote").id

    response = client.post(
        f"/api/dataset/{dataset_id}/{path}", json={"provider": provider})

    assert response.status_code == 400
    assert response.get_json()["code"] == "external_image_consent_required"


@pytest.mark.parametrize("provider", ["openai", "chatgpt", "gemini"])
def test_remote_classification_passes_provider_without_gpu_window(
        client, app, monkeypatch, provider):
    from app.config import LOCAL_USER
    from app.routes import datasets
    from app.services import face_dataset_service as service

    with app.app_context():
        dataset_id = service.create_dataset(LOCAL_USER, "Remote", "remote").id
    seen = {}
    monkeypatch.setattr(service, "classify_images",
                        lambda user_id, ds_id, provider=None: seen.update(
                            user_id=user_id, dataset_id=ds_id, provider=provider) or 3)
    monkeypatch.setattr(datasets, "gpu_exclusive_vision_window",
                        lambda **kwargs: pytest.fail("remote classification must not pause ComfyUI"))

    response = client.post(f"/api/dataset/{dataset_id}/classify", json={
        "provider": provider, "allow_external_images": True,
    })

    assert response.status_code == 200
    assert response.get_json()["classified"] == 3
    assert seen["provider"] == provider
