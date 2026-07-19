"""Scrape SCAN + THUMB proxy (read-only) — feeds the concept-dataset builder.

Only two endpoints are lifted from the source app's scrape blueprint, and only
their READ-ONLY parts: `/api/scrape/scan` (URL → list of media items via the
ported sources engine, downloads nothing) and `/api/scrape/thumb` (server-side
fetch of a remote thumbnail the browser can't hotlink). The shared download
pool, quota (ScrapeScanLog) and admin/category gates are dropped — this app is a
single local user. The anti-SSRF guards (`_validate_public_http_url`, no-redirect
fetch, content-type + size caps) are KEPT: the server still fetches arbitrary
user-supplied URLs.

Actually pulling the chosen images INTO a dataset is a separate, autonomous path
(`POST /api/dataset/<id>/scrape-import` in routes/datasets.py → svc.scrape_import_urls).
"""
from flask import Blueprint, request, jsonify, Response

from ..scrape.netfetch import _validate_public_http_url, fetch_hardened_bytes

bp = Blueprint('scrape', __name__, url_prefix='/api')

MAX_SCAN_PAGE = 50
MAX_THUMB_BYTES = 12 * 1024 * 1024  # 12 MB
_ALLOWED_THUMB_TYPES = {'image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/avif'}


@bp.post('/scrape/scan')
def scrape_scan():
    """List the downloadable media of a URL via the sources registry (read-only).

    Body: {"url": "...", "page": 0, "include_albums": false}. include_albums
    only matters for gallery-listing sources (PornPics category/tag/search):
    false (default) returns one cover per matched gallery, true dives into every
    photo of each gallery. Returns {scannable, platform, url_type, count, items,
    paginated, page, category} (200), {error, suggestions} (400), or {error}
    (502) on a source-level failure. Downloads nothing."""
    data = request.get_json(silent=True) or {}
    url = data.get('url')
    if not url or not isinstance(url, str):
        return jsonify({'error': 'URL missing.'}), 400
    if len(url) > 2048:
        return jsonify({'error': 'URL too long.'}), 400
    # "Load more" pagination (paginable sources): 0-based, hard-capped (deep pages
    # make gallery-dl re-paginate the whole listing → slow + abuse vector).
    try:
        page = int(data.get('page', 0))
    except (TypeError, ValueError):
        page = 0
    page = max(0, min(page, MAX_SCAN_PAGE))

    from ..scrape.validators import url_validator
    result = url_validator.validate_url(url)
    if not result.is_valid:
        return jsonify({'error': result.error or 'invalid URL',
                        'suggestions': result.suggestions}), 400

    from ..scrape.sources import registry  # local import: avoid an import cycle at load
    match = registry.resolve(url)
    if match is None or match.source is None:
        return jsonify({'error': result.error or 'unsupported URL.',
                        'suggestions': result.suggestions or
                        ['Check the URL is a reachable media page.']}), 400

    match.page = page
    match.include_albums = bool(data.get('include_albums'))
    items, err = match.source.scan(match)
    if err:
        return jsonify({'error': err, 'platform': result.platform.value,
                        'url_type': result.url_type.value}), 502
    return jsonify({
        'scannable': True, 'platform': result.platform.value,
        'url_type': result.url_type.value,
        'count': len(items or []), 'items': items or [],
        'paginated': bool(getattr(match.source, 'paginated', False)),
        'page': page,
        'category': getattr(match.source, 'category', 'video'),
    })


@bp.get('/scrape/thumb')
def scrape_thumb():
    """Thumbnail proxy. Source CDNs block direct hotlinking (referer/CORS) so the
    browser <img> fails; fetch server-side (curl_cffi impersonate=chrome + Referer)
    and restream from our origin. SSRF-guarded (public http(s) only, no redirects),
    content-type restricted to raster, size-capped."""
    if request.headers.get('Sec-Fetch-Site', '').lower() in ('cross-site', 'none'):
        return jsonify({'error': 'cross-site thumbnail requests are refused'}), 403
    url = (request.args.get('url') or '').strip()
    ok, err = _validate_public_http_url(url)
    if not ok:
        return jsonify({'error': err or 'invalid URL'}), 400
    ok, data, ctype, reason = fetch_hardened_bytes(
        url, allowed_types=_ALLOWED_THUMB_TYPES, max_bytes=MAX_THUMB_BYTES,
        require_image_magic=True)
    if not ok:
        status = {
            'ssrf': 400, 'no_curl': 503, 'toolarge': 413,
            'type': 415, 'noimage': 415,
        }.get(reason, 502)
        message = {
            'ssrf': 'invalid URL', 'no_curl': 'curl_cffi unavailable',
            'toolarge': 'thumbnail too large', 'type': 'unsupported type',
            'noimage': 'response is not a supported raster image',
            'redirect': 'redirect refused',
        }.get(reason, 'fetch failed')
        return jsonify({'error': message}), status
    # Hardened: no MIME sniffing, inline, locked-down CSP (defense in depth).
    return Response(data, content_type=ctype, headers={
        'Cache-Control': 'public, max-age=86400',
        'X-Content-Type-Options': 'nosniff',
        'Content-Disposition': 'inline; filename="thumb"',
        'Content-Security-Policy': "default-src 'none'; sandbox",
    })
