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
    assert seen['timeout'] == 30
    assert 'secureCloud: true' in seen['json']['query']
    assert len(rc.search_offers(24, 0.8, 1)) == 1
    monkeypatch.setattr(rc.cfg, 'get', lambda *a: 'COMMUNITY')
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


@pytest.mark.parametrize('status,expected', [(200, True), (202, True), (204, True), (404, True), (409, False), (500, False)])
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


@pytest.mark.parametrize('instance', [None, {}, {'actual_status': 'running'}])
def test_base_url_requires_instance_id(rc, instance):
    assert rc.derive_base_url(instance, 8675) is None


@pytest.mark.parametrize('operation', ['search', 'get', 'list'])
@pytest.mark.parametrize('status', [401, 500])
def test_http_error_contains_status_and_body(rc, monkeypatch, operation, status):
    monkeypatch.setattr(rc.requests, 'request', lambda *a, **k: FakeResp(status, 'failure detail'))
    calls = {'search': lambda: rc.search_offers(24, 0.8),
             'get': lambda: rc.get_instance('pod'), 'list': rc.list_instances}
    with pytest.raises(rc.RunpodError, match=f'HTTP {status}: failure detail'):
        calls[operation]()


@pytest.mark.parametrize('error', [ValueError, TypeError])
def test_malformed_json(rc, monkeypatch, error):
    class MalformedResp(FakeResp):
        def json(self):
            raise error('bad body')

    monkeypatch.setattr(rc.requests, 'request', lambda *a, **k: MalformedResp())
    with pytest.raises(rc.RunpodError, match='^RunPod returned malformed JSON$'):
        rc.graphql('{}')


@pytest.mark.parametrize('body', [{'errors': [{'message': 'denied'}], 'data': {}},
                                 {'data': None}, {'data': []}, []])
def test_graphql_invalid_response(rc, monkeypatch, body):
    monkeypatch.setattr(rc.requests, 'request', lambda *a, **k: FakeResp(200, body))
    with pytest.raises(rc.RunpodError, match='GraphQL returned an invalid response or errors'):
        rc.graphql('{}')


@pytest.mark.parametrize('data', [{}, {'gpuTypes': None}, {'gpuTypes': []}])
def test_empty_catalogue(rc, monkeypatch, data):
    monkeypatch.setattr(rc.requests, 'request', lambda *a, **k: FakeResp(200, {'data': data}))
    assert rc.search_offers(24, 0.8) == []


@pytest.mark.parametrize('field,value', [('lowestPrice', None), ('memoryInGb', None),
                                        ('memoryInGb', 'missing'), ('id', ''), ('id', 'missing')])
def test_incomplete_gpu_is_filtered(rc, monkeypatch, field, value):
    gpu = {'id': 'gpu', 'memoryInGb': 24,
           'lowestPrice': {'uninterruptablePrice': 0.4, 'stockStatus': 'High'}}
    if value == 'missing':
        gpu.pop(field)
    else:
        gpu[field] = value
    monkeypatch.setattr(rc.requests, 'request', lambda *a, **k: FakeResp(200, {'data': {'gpuTypes': [gpu]}}))
    assert rc.search_offers(24, 0.8) == []


def test_catalogue_limit_keeps_cheapest_and_includes_cap(rc, monkeypatch):
    gpus = [{'id': name, 'memoryInGb': 24,
             'lowestPrice': {'uninterruptablePrice': price, 'stockStatus': 'High'}}
            for name, price in [('cap', 0.8), ('cheap', 0.2), ('middle', 0.5)]]
    monkeypatch.setattr(rc.requests, 'request', lambda *a, **k: FakeResp(200, {'data': {'gpuTypes': gpus}}))
    assert [o['offer_id'] for o in rc.search_offers(24, 0.8)] == ['cheap', 'middle', 'cap']
    assert [o['offer_id'] for o in rc.search_offers(24, 0.8, limit=2)] == ['cheap', 'middle']


@pytest.mark.parametrize('cloud_type', ['COMMUNITY', '', None])
@pytest.mark.parametrize('env', [None, {'AI_TOOLKIT_AUTH': 'token', '-e FOO': 'bar'}])
def test_create_config_defaults(rc, monkeypatch, cloud_type, env):
    settings = {'cloud.runpod.ui_port': 9000, 'cloud.runpod.image': 'configured-image',
                'cloud.runpod.cloud_type': cloud_type}
    monkeypatch.setattr(rc.cfg, 'get', settings.get)
    seen = {}

    def request(method, url, **kw):
        seen.update(kw)
        assert method == 'POST'
        assert url == rc.API_BASE + '/pods'
        return FakeResp(201, {'id': 'pod'})

    monkeypatch.setattr(rc.requests, 'request', request)
    assert rc.create_instance('gpu', 60, 'lds-run', template_hash='template', env=env) == 'pod'
    assert seen['timeout'] == 30
    assert seen['headers']['Authorization'] == 'Bearer test-key'
    assert 'params' not in seen
    assert seen['json']['ports'] == ['9000/http']
    assert seen['json']['imageName'] == 'configured-image'
    assert seen['json']['cloudType'] == (cloud_type or 'SECURE')
    assert seen['json']['templateId'] == 'template'
    assert seen['json']['env'] == ({'AI_TOOLKIT_AUTH': 'token'} if env else {})


@pytest.mark.parametrize('status,body', [(500, 'capacity unavailable'), (401, 'invalid api key')])
def test_create_generic_error(rc, monkeypatch, status, body):
    monkeypatch.setattr(rc.requests, 'request', lambda *a, **k: FakeResp(status, body))
    with pytest.raises(rc.RunpodError, match=f'^RunPod returned HTTP {status}: {body}$'):
        rc.create_instance('gpu', 60, 'lds-run')


@pytest.mark.parametrize('body', [{}, {'id': None}, {'id': ''}, {'id': 123}, [], {'id': '  '}])
def test_create_requires_valid_id(rc, monkeypatch, body):
    monkeypatch.setattr(rc.requests, 'request', lambda *a, **k: FakeResp(201, body))
    with pytest.raises(rc.RunpodError, match='^RunPod create succeeded without a valid pod id$'):
        rc.create_instance('gpu', 60, 'lds-run')


@pytest.mark.parametrize('operation,body,message', [('list', {}, 'invalid pod list'), ('get', [], 'invalid pod')])
def test_invalid_pod_body(rc, monkeypatch, operation, body, message):
    monkeypatch.setattr(rc.requests, 'request', lambda *a, **k: FakeResp(200, body))
    with pytest.raises(rc.RunpodError, match=message):
        rc.list_instances() if operation == 'list' else rc.get_instance('pod')


def test_empty_pod_list(rc, monkeypatch):
    monkeypatch.setattr(rc.requests, 'request', lambda *a, **k: FakeResp(200, []))
    assert rc.list_instances() == []


@pytest.mark.parametrize('operation', ['create', 'list', 'get', 'graphql', 'search', 'destroy'])
def test_every_operation_requires_key(rc, monkeypatch, operation):
    monkeypatch.delenv('RUNPOD_API_KEY')
    monkeypatch.setattr(rc.requests, 'request', lambda *a, **k: pytest.fail('HTTP without credentials'))
    calls = {'create': lambda: rc.create_instance('gpu', 60, 'lds-run'),
             'list': rc.list_instances, 'get': lambda: rc.get_instance('pod'),
             'graphql': lambda: rc.graphql('{}'), 'search': lambda: rc.search_offers(24, 0.8),
             'destroy': lambda: rc.destroy_instance('pod')}
    if operation == 'destroy':
        assert calls[operation]() is False
    else:
        with pytest.raises(rc.RunpodError, match='RUNPOD_API_KEY is not configured'):
            calls[operation]()


@pytest.mark.parametrize('operation', ['get', 'graphql'])
def test_network_error_redacts_credentials(rc, monkeypatch, operation):
    def request(*a, **kw):
        raise rc.requests.ConnectionError(rc.GRAPHQL_URL + '?api_key=test-key')

    monkeypatch.setattr(rc.requests, 'request', request)
    with pytest.raises(rc.RunpodError) as exc:
        rc.get_instance('pod') if operation == 'get' else rc.graphql('{}')
    assert str(exc.value) == 'RunPod request failed'
    assert 'test-key' not in str(exc.value)
    assert rc.GRAPHQL_URL not in str(exc.value)


@pytest.mark.parametrize('status', ['missing', None, 'RUNNING'])
@pytest.mark.parametrize('ports', [None, ['8675'], ['22/tcp']])
def test_normalize_incomplete_pod(rc, monkeypatch, status, ports):
    pod = {'id': 42, 'ports': ports}
    if status != 'missing':
        pod['desiredStatus'] = status
    monkeypatch.setattr(rc.requests, 'request', lambda *a, **k: FakeResp(200, pod))
    assert rc.get_instance(42) == {
        'instance_id': '42', 'actual_status': 'running' if status == 'RUNNING' else '',
        'public_ipaddr': None, 'ports': {}, 'label': None, 'dph_total': None,
        'jupyter_token': None,
    }
