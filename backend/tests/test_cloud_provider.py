from types import SimpleNamespace


def test_registry(app, monkeypatch):
    from app.services import cloud_provider as cp
    from app.services import vast_client, runpod_client

    assert set(cp.PROVIDERS) == {'vast', 'runpod'}
    assert cp.PROVIDERS['vast'].client is vast_client
    assert cp.PROVIDERS['runpod'].client is runpod_client
    assert issubclass(vast_client.VastError, cp.ProviderError)
    assert issubclass(runpod_client.RunpodError, cp.ProviderError)
    monkeypatch.setattr(cp.cfg, 'get', lambda *a: 'unknown')
    assert cp.current().name == 'vast'
    assert cp.for_run(SimpleNamespace(provider=None)).name == 'vast'
    assert (
        cp.PROVIDERS['runpod'].console_url('abc')
        == 'https://console.runpod.io/pods/abc'
    )
    assert cp.PROVIDERS['runpod'].console_url() == 'https://console.runpod.io/pods'
    assert cp.PROVIDERS['vast'].console_url('abc') == 'https://cloud.vast.ai/instances/'
    monkeypatch.setattr(
        cp.cfg, 'secret', lambda k: 'key' if k == 'RUNPOD_API_KEY' else ''
    )
    assert [p.name for p in cp.configured()] == ['runpod']
