"""Provider-routing contracts for local vision backends."""

import base64
from unittest.mock import MagicMock, patch


def test_lmstudio_uses_openai_compatible_multimodal_chat(app):
    from app import config as cfg
    from app.services import vision_ollama

    cfg.save_config({
        'local_vision': {'backend': 'lmstudio'},
        'lmstudio': {'url': 'http://127.0.0.1:1234/v1', 'vision_model': 'qwen-vl'},
    })
    response = MagicMock(status_code=200)
    response.json.return_value = {
        'choices': [{'message': {'content': 'A close portrait.'}}],
    }

    with patch('app.services.vision_ollama.requests.post', return_value=response) as post:
        result = vision_ollama.describe_image_ollama(b'image', 'Describe it')

    assert result == 'A close portrait.'
    assert post.call_args.args[0] == 'http://127.0.0.1:1234/v1/chat/completions'
    body = post.call_args.kwargs['json']
    assert body['model'] == 'qwen-vl'
    content = body['messages'][0]['content']
    assert content[0] == {'type': 'text', 'text': 'Describe it'}
    assert content[1]['image_url']['url'] == (
        'data:image/webp;base64,' + base64.b64encode(b'image').decode('ascii'))


def test_llamacpp_uses_json_response_format_for_structured_passes(app):
    from app import config as cfg
    from app.services import vision_ollama

    cfg.save_config({
        'local_vision': {'backend': 'llamacpp'},
        'llamacpp': {'url': 'http://127.0.0.1:8080/v1', 'vision_model': 'qwen-vl.gguf'},
    })
    response = MagicMock(status_code=200)
    response.json.return_value = {
        'choices': [{'message': {'content': '{"framing":"close"}'}}],
    }

    with patch('app.services.vision_ollama.requests.post', return_value=response) as post:
        result = vision_ollama.describe_image_ollama(
            b'image', 'Classify it', prefer_json=True, fmt='json')

    assert result == '{"framing":"close"}'
    assert post.call_args.kwargs['json']['response_format'] == {'type': 'json_object'}


def test_openai_compatible_failure_does_not_try_to_start_ollama(app):
    from app import config as cfg
    from app.services import vision_ollama

    cfg.save_config({
        'local_vision': {'backend': 'lmstudio'},
        'lmstudio': {'url': 'http://127.0.0.1:1234/v1', 'vision_model': 'qwen-vl'},
    })

    with patch('app.services.vision_ollama.requests.post', side_effect=OSError('down')):
        with patch('app.services.ollama_control.ensure_captioning_ready') as start:
            try:
                vision_ollama.describe_image_ollama(
                    b'image', 'Describe it', auto_start_local=True)
            except RuntimeError as exc:
                assert 'LM Studio' in str(exc)
            else:
                raise AssertionError('expected the unavailable provider to be reported')
    start.assert_not_called()


def test_local_vision_probe_requires_configured_model_to_be_loaded(app):
    from app import capabilities, config as cfg

    cfg.save_config({
        'local_vision': {'backend': 'lmstudio'},
        'lmstudio': {'url': 'http://127.0.0.1:1234/v1', 'vision_model': 'wanted-vl'},
    })
    response = MagicMock(status_code=200)
    response.json.return_value = {'data': [{'id': 'other-model'}]}

    with patch('app.capabilities.requests.get', return_value=response):
        result = capabilities.probe_local_vision()

    assert result['reachable'] is True
    assert result['model_ready'] is False
    assert result['provider'] == 'lmstudio'
