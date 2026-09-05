"""RunPod contracts, fully mocked at the requests boundary."""

import pytest

from test_vast_client import FakeResp


@pytest.fixture()
def rc(app, monkeypatch):
    monkeypatch.setenv('RUNPOD_API_KEY', 'test-key')
    from app.services import runpod_client

    return runpod_client


def test_catalogue(rc, monkeypatch):
    seen = {}

    def gpu(name, memory=24, price=0.4, stock='High'):
        return {
            'id': name,
            'displayName': name,
            'memoryInGb': memory,
            'lowestPrice': {'uninterruptablePrice': price, 'stockStatus': stock},
        }

    def request(method, url, **kw):
        seen.update(kw)
        assert url == rc.GRAPHQL_URL
        return FakeResp(
            200,
            {
                'data': {
                    'gpuTypes': [
                        gpu('expensive', price=0.7),
                        gpu('cheap'),
                        gpu('small', memory=16),
                        gpu('over', price=1),
                        gpu('unpriced', price=None),
                        gpu('empty', stock='None'),
                        gpu('missing', stock=None),
                    ]
                }
            },
        )

    monkeypatch.setattr(rc.requests, 'request', request)
    offers = rc.search_offers(24, 0.8)
    assert [o['offer_id'] for o in offers] == ['cheap', 'expensive']
    assert offers[0] == {
        'offer_id': 'cheap',
        'gpu_name': 'cheap',
        'gpu_ram_gb': 24,
        'dph_total': 0.4,
        'machine_id': None,
        'reliability': None,
        'stock_status': 'High',
    }
    assert seen['headers']['Authorization'] == 'Bearer test-key'
    assert seen['params'] == {'api_key': 'test-key'}
    assert 'secureCloud: true' in seen['json']['query']
    assert len(rc.search_offers(24, 0.8, 1)) == 1
    rc.cfg.save_config({'cloud': {'runpod': {'cloud_type': 'COMMUNITY'}}})
    rc.search_offers(24, 0.8)
    assert 'secureCloud: false' in seen['json']['query']


@pytest.mark.parametrize('template', [None, 'template-1'])
def test_create(rc, monkeypatch, template):
    seen = {}

    def request(method, url, **kw):
        assert method == 'POST' and url == rc.API_BASE + '/pods'
        seen.update(kw['json'])
        return FakeResp(201, {'id': 'pod'})

    monkeypatch.setattr(rc.requests, 'request', request)
    assert (
        rc.create_instance(
            'GPU',
            60,
            'lds-1',
            template,
            'image',
            {'AI_TOOLKIT_AUTH': 'token', '-p 8675:8675': '1'},
        )
        == 'pod'
    )
    expected = {
        'name': 'lds-1',
        'imageName': 'image',
        'gpuTypeIds': ['GPU'],
        'gpuCount': 1,
        'cloudType': 'SECURE',
        'containerDiskInGb': 60,
        'volumeInGb': 0,
        'ports': ['8675/http'],
        'env': {'AI_TOOLKIT_AUTH': 'token'},
    }
    if template:
        expected['templateId'] = template
    assert seen == expected


def test_no_capacity(rc, monkeypatch):
    monkeypatch.setattr(
        rc.requests, 'request', lambda *a, **k: FakeResp(400, 'out of stock')
    )
    with pytest.raises(rc.RunpodError, match='RTX 4090.*GPU picker'):
        rc.create_instance('RTX 4090', 60, 'lds-1')


def test_get_and_list(rc, monkeypatch):
    pod = {
        'id': 'abc',
        'desiredStatus': 'RUNNING',
        'name': 'lds-1',
        'costPerHr': 0.55,
        'ports': ['8675/http', '22/tcp'],
    }
    monkeypatch.setattr(rc.requests, 'request', lambda *a, **k: FakeResp(200, pod))
    inst = rc.get_instance('abc')
    assert inst['dph_total'] == 0.55 and inst['jupyter_token'] is None
    assert inst['ports'] == {
        '8675/tcp': [{'HostIp': 'abc-8675.proxy.runpod.net', 'HostPort': 443}]
    }
    assert rc.derive_base_url(inst, 8675) == 'https://abc-8675.proxy.runpod.net'
    monkeypatch.setattr(rc.requests, 'request', lambda *a, **k: FakeResp(200, [pod]))
    assert rc.list_instances() == [inst]
    pod['desiredStatus'] = 'EXITED'
    monkeypatch.setattr(rc.requests, 'request', lambda *a, **k: FakeResp(200, pod))
    assert rc.get_instance('abc')['ports'] == {}
    assert rc.derive_base_url(rc.get_instance('abc'), 8675) is None
    monkeypatch.setattr(rc.requests, 'request', lambda *a, **k: FakeResp(404))
    assert rc.get_instance('abc') is None


@pytest.mark.parametrize('status,expected', [(204, True), (404, True), (500, False)])
def test_destroy(rc, monkeypatch, status, expected):
    monkeypatch.setattr(rc.requests, 'request', lambda *a, **k: FakeResp(status))
    assert rc.destroy_instance('abc') is expected


def test_network_error(rc, monkeypatch):
    def fail(*a, **k):
        raise rc.requests.ConnectionError('failed')

    monkeypatch.setattr(rc.requests, 'request', fail)
    assert rc.destroy_instance('abc') is False
    with pytest.raises(rc.RunpodError):
        rc.list_instances()


def test_missing_key(rc, monkeypatch):
    monkeypatch.delenv('RUNPOD_API_KEY')
    with pytest.raises(rc.RunpodError, match='RUNPOD_API_KEY'):
        rc.search_offers(24, 0.8)
