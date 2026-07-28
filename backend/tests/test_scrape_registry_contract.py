import json
import io
from types import SimpleNamespace

import pytest
from PIL import Image


@pytest.mark.parametrize(('url', 'source_name'), [
    ('https://www.redgifs.com/users/example', 'redgifs'),
    ('https://www.instagram.com/example/', 'instagram'),
    ('https://picazor.com/fr/example/', 'picazor'),
    ('https://www.erome.com/a/example', 'erome'),
    ('https://coomer.st/onlyfans/user/example', 'coomer'),
    ('https://kemono.cr/patreon/user/1', 'kemono'),
    ('https://bunkr.cr/a/example', 'bunkr'),
    ('https://cyberdrop.me/a/example', 'cyberdrop'),
    ('https://x.com/example/media', 'x'),
    ('https://www.tiktok.com/@example', 'tiktok'),
    ('https://www.pornpics.com/galleries/example/', 'pornpics'),
    ('https://civitai.com/tag/example', 'civitai'),
    ('https://fapello.com/example/', 'fapello'),
    ('https://www.reddit.com/r/pics/', 'reddit'),
    ('https://www.sex.com/search/pics?query=example', 'sexcom'),
    ('https://example.org/video/123', 'universal'),
])
def test_every_registered_scrape_adapter_has_offline_resolution_fixture(url, source_name):
    from app.scrape.sources import registry

    match = registry.resolve(url)

    assert match is not None
    assert match.source.name == source_name


def test_registry_match_failure_is_isolated_and_falls_back(monkeypatch):
    from app.scrape.sources import registry

    failing = next(source for source in registry.all_sources()
                   if source.name != 'universal')
    monkeypatch.setattr(failing, 'match', lambda url: (_ for _ in ()).throw(
        RuntimeError('offline adapter failure')))

    match = registry.resolve('https://example.org/video/123')

    assert match is not None and match.source.name == 'universal'


def test_registered_adapter_names_and_universal_fallback_are_unique():
    from app.scrape.sources import registry

    sources = registry.all_sources()
    names = [source.name for source in sources]
    assert len(names) == len(set(names))
    assert [source.name for source in sources
            if source.capabilities.is_universal_fallback] == ['universal']


def test_every_registered_adapter_executes_offline_scan_contract(app, monkeypatch):
    """Run every production parser with only I/O boundaries replaced.

    This deliberately does not replace ``Source.scan`` or ``gdl.enumerate``:
    registered adapters must execute their real URL normalization, parser and
    common-item mapping before their advertised output reaches dataset import.
    """
    from app.scrape.sources import registry
    from app.scrape.sources import gdl, image_sites, instagram, picazor, reddit
    from app.scrape.sources import redgifs, sexcom
    from app.scrape import netfetch
    from app.services import face_dataset_service as dataset_service
    from app.config import LOCAL_USER

    image_bytes = io.BytesIO()
    Image.new('RGB', (1280, 960), (70, 120, 180)).save(image_bytes, 'PNG')
    monkeypatch.setattr(
        dataset_service, '_download_scrape_item',
        lambda item: ('ok', image_bytes.getvalue(), item['url']))

    # gallery-dl is a process boundary. Its JSON messages still flow through
    # the real recursive parser, deduper and media normalizer.
    monkeypatch.setattr(netfetch, '_validate_public_http_url',
                        lambda url: (True, None))
    gdl_payload = json.dumps([
        [3, 'https://cdn.example.test/fixture.jpg',
         {'title': 'fixture', 'extension': 'jpg'}],
    ])
    monkeypatch.setattr(gdl.subprocess, 'run', lambda *args, **kwargs:
                        SimpleNamespace(stdout=gdl_payload, stderr='', returncode=0))

    # HTTP/API/client-library boundaries for bespoke parsers.
    class OfflineResponse:
        status_code = 200
        headers = {}

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    redgifs.client._token = None
    monkeypatch.setattr(redgifs.client._session, 'get', lambda url, **kwargs:
                        OfflineResponse(
                            {'token': 'offline-token'} if '/auth/' in url else {
                                'gifs': [{
                                    'id': 'fixture',
                                    'urls': {'thumbnail':
                                             'https://cdn.example.test/thumb.jpg'},
                                    'duration': 2,
                                }],
                                'pages': 1,
                            }))
    monkeypatch.setattr(picazor, '_request_html', lambda url: (
        '<img src="/uploads/model/300px_fixture.jpg">', None))
    monkeypatch.setattr(image_sites, '_listing_html', lambda url: (
        '<a class="rel-link" href="/galleries/fixture"><img '
        'data-src="https://cdn.example.test/460/fixture.jpg" alt="fixture"></a>'))
    monkeypatch.setattr(sexcom, '_search_json', lambda params, page: {
        'data': [{'uri': '/fixture.jpg', 'title': 'fixture'}],
        'paging': {'numberOfPages': 1},
    })
    reddit._token_cache.update(value=None, exp=0.0, cid=None)
    monkeypatch.setenv('REDDIT_CLIENT_ID', 'offline-client')
    monkeypatch.setattr(reddit.requests, 'post', lambda *args, **kwargs:
                        OfflineResponse({'access_token': 'offline-token',
                                         'expires_in': 3600}))
    monkeypatch.setattr(reddit.requests, 'get', lambda *args, **kwargs:
                        OfflineResponse({
                            'data': {'after': None, 'children': [{'data': {
                                'title': 'fixture', 'subreddit': 'pics',
                                'url_overridden_by_dest':
                                    'https://i.redd.it/fixture.jpg',
                            }}]},
                        }))

    class OfflinePost:
        shortcode = 'fixture'
        typename = 'GraphImage'
        is_video = False
        url = 'https://cdn.example.test/instagram.jpg'

    monkeypatch.setattr(instagram, 'INSTALOADER_AVAILABLE', True)
    monkeypatch.setattr(instagram, '_build_loader',
                        lambda: SimpleNamespace(context=object()))
    monkeypatch.setattr(instagram, 'instaloader', SimpleNamespace(
        Post=SimpleNamespace(from_shortcode=lambda context, shortcode: OfflinePost()),
        QueryReturnedNotFoundException=RuntimeError,
    ))

    urls = {
        'redgifs': 'https://www.redgifs.com/users/example',
        'instagram': 'https://www.instagram.com/p/fixture/',
        'picazor': 'https://picazor.com/fr/videos/week',
        'erome': 'https://www.erome.com/a/example',
        'coomer': 'https://coomer.st/onlyfans/user/example',
        'kemono': 'https://kemono.cr/patreon/user/1',
        'bunkr': 'https://bunkr.cr/a/example',
        'cyberdrop': 'https://cyberdrop.me/a/example',
        'x': 'https://x.com/example/media',
        'tiktok': 'https://www.tiktok.com/@example',
        'pornpics': 'https://www.pornpics.com/example/',
        'civitai': 'https://civitai.com/tag/example',
        'fapello': 'https://fr.fapello.com/example/',
        'reddit': 'https://www.reddit.com/r/pics/',
        'sexcom': 'https://www.sex.com/pics?search=example',
        'universal': 'https://example.org/video/123',
    }

    executed = set()
    for source in registry.all_sources():
        match = registry.resolve(urls[source.name])
        assert match is not None and match.source is source
        items, error = source.scan(match)
        assert error is None
        assert items and all(
            isinstance(item.get('url'), str)
            and item['url'].startswith(('http://', 'https://'))
            and item.get('type') in ('image', 'video')
            and item.get('platform')
            for item in items)
        # Images are the records accepted by scrape-import: the media URL, not
        # a thumbnail-only placeholder, must be directly fetchable.
        for item in items:
            if item['type'] == 'image':
                assert item['url'] != item.get('thumbnail') or item['url'].rsplit(
                    '?', 1)[0].lower().endswith(
                        ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.avif'))
        importable = next((item for item in items if item['type'] == 'image'), None)
        if importable is not None:
            with app.app_context():
                dataset = dataset_service.create_dataset(
                    LOCAL_USER, f"scan-{source.name}", f"scan_{source.name}",
                    kind='concept', concept_desc='offline parser boundary fixture')
                result = dataset_service.scrape_import_urls(
                    LOCAL_USER, dataset.id, [importable])
                assert result['imported'] == 1, (source.name, result, importable)
        executed.add(source.name)
    assert executed == {source.name for source in registry.all_sources()}


@pytest.mark.parametrize(
    ('stdout', 'returncode', 'stderr', 'expected'),
    [
        ('not-json', 0, '', 'réponse illisible'),
        (json.dumps([[-1, {'message': 'extractor blocked'}]]), 0, '',
         'extractor blocked'),
        (json.dumps([[3, 'https://cdn.example.test/partial.jpg',
                      {'extension': 'jpg'}]]), 4, 'HTTP 503',
         'résultats partiels'),
    ],
)
def test_real_gallery_dl_parser_preserves_critical_failure_contracts(
        monkeypatch, stdout, returncode, stderr, expected):
    """Malformed, sentinel and partial process output retain distinct meaning."""
    from app.scrape import netfetch
    from app.scrape.sources import gdl

    monkeypatch.setattr(netfetch, '_validate_public_http_url',
                        lambda url: (True, None))
    monkeypatch.setattr(gdl.subprocess, 'run', lambda *args, **kwargs:
                        SimpleNamespace(stdout=stdout, stderr=stderr,
                                        returncode=returncode))

    items, diagnostic = gdl.enumerate(
        'https://civitai.com/tag/offline', platform='civitai')

    assert expected in diagnostic
    if returncode == gdl.EXIT_HTTP:
        assert items and items[0]['url'].endswith('partial.jpg')
    else:
        assert items is None
