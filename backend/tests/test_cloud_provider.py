from types import SimpleNamespace

import pytest


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


@pytest.mark.parametrize('name', ['', None, 'RUNPOD', 'Vast'])
def test_current_falls_back_case_sensitively(app, monkeypatch, name):
    from app.services import cloud_provider as cp

    monkeypatch.setattr(cp.cfg, 'get', lambda *a: name)
    assert cp.current() is cp.PROVIDERS['vast']


@pytest.mark.parametrize('run', [SimpleNamespace(provider='lambda'), SimpleNamespace()])
def test_unknown_or_missing_run_provider_is_vast(app, run):
    from app.services import cloud_provider as cp

    assert cp.for_run(run) is cp.PROVIDERS['vast']


@pytest.mark.parametrize('name', ['vast', 'runpod'])
@pytest.mark.parametrize('template', ['', '  template-id  '])
@pytest.mark.parametrize('port', [None, 0, 8675, 9000])
def test_boot_settings_and_ui_port(app, monkeypatch, name, template, port):
    from app.services import cloud_provider as cp

    settings = {'template_hash' if name == 'vast' else 'template_id': template}
    if port is not None:
        settings['ui_port'] = port
    cloud = settings if name == 'vast' else {'runpod': settings}
    monkeypatch.setattr(cp.cfg, 'get', lambda *a: cloud)
    expected_port = port or (18675 if name == 'vast' else 8675)
    if name == 'vast' and template and port == 8675:
        expected_port = 18675
    provider = cp.PROVIDERS[name]
    assert provider.boot_settings(cloud) == (template.strip(), expected_port)
    assert provider.ui_port == expected_port


def test_runpod_boot_settings_missing_nested_config(app):
    from app.services import cloud_provider as cp

    assert cp.PROVIDERS['runpod'].boot_settings({}) == ('', 8675)


@pytest.mark.parametrize('keys,expected', [([], []), (['VAST_API_KEY'], ['vast']),
                                        (['RUNPOD_API_KEY'], ['runpod']),
                                        (['VAST_API_KEY', 'RUNPOD_API_KEY'], ['vast', 'runpod'])])
def test_configured_provider_order(app, monkeypatch, keys, expected):
    from app.services import cloud_provider as cp

    monkeypatch.setattr(cp.cfg, 'secret', lambda key: 'key' if key in keys else '')
    # Reconciliation visits vast before RunPod; launch tests rely on this order.
    assert [provider.name for provider in cp.configured()] == expected


@pytest.mark.parametrize('iid,suffix', [(None, ''), ('', ''), (42, '/42')])
def test_provider_console_urls(app, iid, suffix):
    from app.services import cloud_provider as cp

    assert cp.PROVIDERS['runpod'].console_url(iid) == 'https://console.runpod.io/pods' + suffix
    assert cp.PROVIDERS['vast'].console_url(iid) == 'https://cloud.vast.ai/instances/'
