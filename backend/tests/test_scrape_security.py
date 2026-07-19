"""Regression tests for the shared remote-media security boundary."""
import ipaddress
import socket
import sys
import types
from urllib.parse import urlparse


def test_ssrf_guard_accepts_only_globally_routable_addresses():
    from app.scrape import netfetch

    assert netfetch._ip_is_blocked(ipaddress.ip_address('127.0.0.1'))
    assert netfetch._ip_is_blocked(ipaddress.ip_address('100.64.0.1'))
    assert not netfetch._ip_is_blocked(ipaddress.ip_address('8.8.8.8'))


def test_url_guard_rejects_credentials_and_invalid_ports_without_dns():
    from app.scrape import netfetch

    assert netfetch._validate_public_http_url(
        'https://user:secret@example.com/image.jpg')[0] is False
    assert netfetch._validate_public_http_url(
        'https://example.com:99999/image.jpg')[0] is False


def test_shared_media_fetch_revalidates_url_before_network(app, monkeypatch):
    from app.scrape import netfetch

    monkeypatch.setattr(
        netfetch, '_validate_public_http_url',
        lambda url: (False, 'internal address'))
    with app.app_context():
        ok, data, ctype, reason = netfetch.fetch_hardened_bytes(
            'https://attacker.example/image.jpg',
            allowed_types={'image/jpeg'}, max_bytes=1024,
            require_image_magic=True)

    assert (ok, data, ctype, reason) == (False, None, None, 'ssrf')


def test_dns_resolution_rejects_mixed_public_and_private_answers(monkeypatch):
    from app.scrape import netfetch

    monkeypatch.setattr(netfetch.socket, 'getaddrinfo', lambda *_args, **_kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443)),
    ])

    ips, error = netfetch._resolve_public_ips('mixed.example', 443)
    assert ips is None
    assert 'interne' in error


def test_shared_media_fetch_pins_the_approved_address(app, monkeypatch):
    from app.scrape import netfetch

    captured = {}

    class Response:
        status_code = 200
        headers = {'content-type': 'image/png'}

        def iter_content(self, _size):
            yield b'\x89PNG\r\n\x1a\n' + b'0' * 16

        def close(self):
            pass

    fake_requests = types.SimpleNamespace(
        get=lambda _url, **kwargs: captured.update(kwargs) or Response())
    fake_module = types.ModuleType('curl_cffi')
    fake_module.requests = fake_requests
    monkeypatch.setitem(sys.modules, 'curl_cffi', fake_module)
    monkeypatch.setattr(
        netfetch, '_validated_public_target',
        lambda _url: (urlparse('https://media.example/image.png'),
                      ('8.8.8.8',), None))

    with app.app_context():
        result = netfetch.fetch_hardened_bytes(
            'https://media.example/image.png', allowed_types={'image/png'},
            max_bytes=1024, require_image_magic=True)

    assert result[0] is True
    assert captured['resolve'] == ['media.example:443:8.8.8.8']
    assert captured['allow_redirects'] is False


def test_ytdlp_entrypoint_revalidates_url_before_subprocess(monkeypatch, tmp_path):
    from app.scrape import netfetch

    monkeypatch.setattr(
        netfetch, '_validate_public_http_url',
        lambda url: (False, 'internal address'))
    monkeypatch.setattr(
        netfetch, '_download_with_ytdlp',
        lambda *args: (_ for _ in ()).throw(AssertionError('must not spawn')))

    assert netfetch.download_via_ytdlp(
        'https://attacker.example/video', str(tmp_path / 'result')) == (
            False, None, 'internal address')


def test_gallery_dl_entrypoints_revalidate_url_before_subprocess(monkeypatch, tmp_path):
    from app.scrape import netfetch
    from app.scrape.sources import gdl

    monkeypatch.setattr(
        netfetch, '_validate_public_http_url',
        lambda url: (False, 'internal address'))
    monkeypatch.setattr(
        gdl.subprocess, 'run',
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('must not spawn')))

    assert gdl._run_simulate(
        'https://attacker.example/gallery', 10, None, None) == (
            None, 'internal address')
    assert gdl.download(
        'https://attacker.example/file', str(tmp_path), 'result') == (
            False, None, 'internal address')


def test_thumbnail_proxy_uses_shared_magic_byte_guard(client, monkeypatch):
    from app.routes import scrape

    monkeypatch.setattr(
        scrape, '_validate_public_http_url', lambda url: (True, None))
    monkeypatch.setattr(
        scrape, 'fetch_hardened_bytes',
        lambda *args, **kwargs: (False, None, None, 'noimage'))

    response = client.get('/api/scrape/thumb?url=https://cdn.example/fake.jpg')

    assert response.status_code == 415
    assert 'raster image' in response.get_json()['error']
