import json
import sys
import types

import pytest

from app.scrape.sources import erome, gdl, instagram, picazor


def test_instagram_image_items_use_distinct_direct_urls():
    class Node:
        is_video = False

        def __init__(self, url):
            self.display_url = url

    post = types.SimpleNamespace(
        shortcode='abc', typename='GraphSidecar',
        get_sidecar_nodes=lambda: [Node('https://cdn.example/1.jpg'),
                                   Node('https://cdn.example/2.jpg')])

    items = instagram._items_from_post(post)

    assert [item['url'] for item in items] == [
        'https://cdn.example/1.jpg', 'https://cdn.example/2.jpg']
    assert {item['page_url'] for item in items} == {'https://www.instagram.com/p/abc/'}


def test_stream_read_failure_is_contained_and_response_closed(app, monkeypatch):
    from app.scrape import netfetch

    class Response:
        status_code = 200
        headers = {'content-type': 'image/jpeg'}
        closed = False

        def iter_content(self, _size):
            yield b'partial'
            raise RuntimeError('connection reset')

        def close(self):
            self.closed = True

    response = Response()
    fake_module = types.ModuleType('curl_cffi')
    fake_module.requests = types.SimpleNamespace(get=lambda *_args, **_kwargs: response)
    monkeypatch.setitem(sys.modules, 'curl_cffi', fake_module)
    monkeypatch.setattr(
        netfetch, '_validated_public_target',
        lambda _url: (types.SimpleNamespace(hostname='media.example', port=None,
                                            scheme='https'), ('8.8.8.8',), None))

    with app.app_context():
        result = netfetch.fetch_hardened_bytes(
            'https://media.example/a.jpg', allowed_types={'image/jpeg'},
            max_bytes=1024, require_image_magic=False)

    assert result == (False, None, None, 'fetch')
    assert response.closed is True


def test_gallery_dl_nonzero_with_output_is_partial(monkeypatch):
    monkeypatch.setattr(gdl, '_validate_for_test', None, raising=False)
    from app.scrape import netfetch
    monkeypatch.setattr(netfetch, '_validate_public_http_url', lambda _url: (True, None))
    monkeypatch.setattr(gdl, '_subprocess_url_allowed', lambda _url: True)
    proc = types.SimpleNamespace(
        returncode=gdl.EXIT_HTTP,
        stdout=json.dumps([[3, 'https://cdn.example/a.jpg', {'extension': 'jpg'}]]),
        stderr='upstream reset')
    monkeypatch.setattr(gdl.subprocess, 'run', lambda *_args, **_kwargs: proc)

    items, warning = gdl.enumerate('https://example.com/gallery')

    assert [item['url'] for item in items] == ['https://cdn.example/a.jpg']
    assert 'partiels' in warning


def test_gallery_dl_deduplicates_albums_and_media(monkeypatch):
    calls = []

    def fake(url, *_args, **_kwargs):
        calls.append(url)
        if url.endswith('/listing'):
            return [[6, 'https://example.com/a', {}],
                    [6, 'https://example.com/a', {}],
                    [6, 'https://example.com/b', {}]], None
        return [[3, 'https://cdn.example/shared.jpg', {'extension': 'jpg'}]], None

    monkeypatch.setattr(gdl, '_run_simulate', fake)
    items, err = gdl.enumerate('https://example.com/listing')

    assert err is None
    assert calls == ['https://example.com/listing', 'https://example.com/a',
                     'https://example.com/b']
    assert [item['url'] for item in items] == ['https://cdn.example/shared.jpg']


def test_gallery_dl_uses_one_overall_deadline(monkeypatch):
    clock = iter([0.0, 10.0, 61.0])
    monkeypatch.setattr(gdl.time, 'monotonic', lambda: next(clock))
    calls = []

    def fake(url, *_args, **kwargs):
        calls.append((url, kwargs['timeout']))
        if url.endswith('/listing'):
            return [[6, 'https://example.com/a', {}],
                    [6, 'https://example.com/b', {}]], None
        return [[3, 'https://cdn.example/a.jpg', {'extension': 'jpg'}]], None

    monkeypatch.setattr(gdl, '_run_simulate', fake)
    items, warning = gdl.enumerate('https://example.com/listing')

    assert [item['url'] for item in items] == ['https://cdn.example/a.jpg']
    assert len(calls) == 2
    assert 'global' in warning


def test_failed_gallery_dl_download_does_not_remove_peer_output(monkeypatch, tmp_path):
    from app.scrape import netfetch
    monkeypatch.setattr(netfetch, '_validate_public_http_url', lambda _url: (True, None))
    monkeypatch.setattr(gdl, '_subprocess_url_allowed', lambda _url: True)
    peer = tmp_path / 'peer.jpg'

    def fail(_cmd, **_kwargs):
        peer.write_bytes(b'peer')
        return types.SimpleNamespace(returncode=4, stdout='', stderr='failed')

    monkeypatch.setattr(gdl.subprocess, 'run', fail)
    result = gdl.download('https://example.com/a', str(tmp_path), 'mine')

    assert result[0] is False
    assert peer.read_bytes() == b'peer'
    assert not list(tmp_path.glob('.gallery-dl-*'))


@pytest.mark.parametrize('module', [erome, picazor])
def test_streamed_download_rejections_close_response(module, monkeypatch, tmp_path):
    from app.scrape import netfetch
    monkeypatch.setattr(netfetch, '_validate_public_http_url', lambda _url: (True, None))

    class Response:
        status_code = 403
        headers = {'content-type': 'text/html'}
        closed = 0

        def close(self):
            self.closed += 1

    response = Response()
    fake_module = types.ModuleType('curl_cffi')
    fake_module.requests = types.SimpleNamespace(get=lambda *_args, **_kwargs: response)
    monkeypatch.setitem(sys.modules, 'curl_cffi', fake_module)

    assert module.download('https://cdn.example/a.jpg', tmp_path / 'out')[0] is False
    assert response.closed == 1


def test_scan_route_validates_boolean_and_reports_partial(client, monkeypatch):
    invalid = client.post('/api/scrape/scan', json={
        'url': 'https://www.pornpics.com/flexible/', 'include_albums': 'false'})
    assert invalid.status_code == 400

    monkeypatch.setattr(
        gdl, '_run_simulate',
        lambda *args, **kwargs: (
            [[3, 'https://cdn.example/a.jpg', {'extension': 'jpg'}]],
            'upstream stopped'))
    response = client.post('/api/scrape/scan', json={
        'url': 'pornpics.com/flexible/', 'include_albums': True})

    assert response.status_code == 200
    assert response.get_json()['partial'] is True
    assert response.get_json()['warning'] == 'upstream stopped'


def test_ytdlp_version_probe_is_cached(app, monkeypatch):
    from app.scrape import netfetch

    calls = []
    monkeypatch.setattr(netfetch, '_version_result', None)
    monkeypatch.setattr(
        netfetch, '_ytdlp_version_tuple',
        lambda: calls.append(True) or netfetch.YTDLP_VERSION_FLOOR)
    with app.app_context():
        assert netfetch._check_ytdlp_version() is True
        assert netfetch._check_ytdlp_version() is True
    assert len(calls) == 1


def test_atomic_download_write_never_exposes_partial_final(tmp_path, monkeypatch):
    from app.scrape.sources import base

    destination = tmp_path / 'image.jpg'
    monkeypatch.setattr(
        base.os, 'replace',
        lambda *_args: (_ for _ in ()).throw(OSError('publish failed')))
    with pytest.raises(OSError, match='publish failed'):
        base.atomic_write_bytes(destination, b'partial bytes')
    assert not destination.exists()
    assert not list(tmp_path.glob('*.tmp'))
