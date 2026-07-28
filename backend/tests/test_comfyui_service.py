from unittest.mock import MagicMock


def test_comfyui_health_uses_current_endpoint_and_bounded_timeout(app, monkeypatch):
    from app.services import comfyui_service as service
    urls = iter(['http://first:8188', 'http://second:8188'])
    monkeypatch.setattr(service, 'api_address', lambda: next(urls))
    get = MagicMock(return_value=MagicMock(status_code=200))
    monkeypatch.setattr(service.requests, 'get', get)

    assert service.ensure_comfyui_before_generation() == (True, 'Running')
    assert service.check_comfyui_status() == {'running': True, 'pid': None}
    assert [call.args[0] for call in get.call_args_list] == [
        'http://first:8188/history', 'http://second:8188/history']
    assert all(call.kwargs['timeout'] == 3 for call in get.call_args_list)


def test_comfyui_health_contains_transport_errors(app, monkeypatch):
    from app.services import comfyui_service as service
    monkeypatch.setattr(service, 'api_address', lambda: 'http://local:8188')
    monkeypatch.setattr(service.requests, 'get',
                        MagicMock(side_effect=service.requests.ConnectionError('offline')))
    assert service.ensure_comfyui_before_generation()[0] is False
    assert service.check_comfyui_status()['running'] is False
