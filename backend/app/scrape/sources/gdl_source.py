# app/scrape/sources/gdl_source.py
"""Base paramétrable des sources gérées par gallery-dl (P4). Une nouvelle source =
sous-classe ~10 lignes : platform_enum + name/priority/capabilities + gdl_opts +
cookies_key. match() = host (via validators.detect_platform) ; scan/download
délèguent au moteur gdl.py."""
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from .base import Source, Match
from . import gdl


def resolve_cookies(key):
    """Chemin du cookies.txt d'une plateforme, ou None. Dossier admin HORS repo :
    $SCRAPE_COOKIES_DIR sinon <COMFYUI_OUTPUT_DIR>/../scrape_cookies. Jamais committé."""
    if not key:
        return None
    base = os.environ.get('SCRAPE_COOKIES_DIR')
    if not base:
        try:
            from ...config import COMFYUI_OUTPUT_DIR
            base = os.path.join(os.path.dirname(COMFYUI_OUTPUT_DIR.rstrip('/\\')), 'scrape_cookies')
        except Exception:
            return None
    path = os.path.join(base, f'{key}.txt')
    return path if os.path.isfile(path) else None


class GalleryDlSource(Source):
    """Source gallery-dl générique. Les sous-classes définissent :
       platform_enum, name, priority, capabilities, gdl_opts (list|None), cookies_key (str|None)."""
    platform_enum = None
    gdl_opts = None
    cookies_key = None

    def _cookies(self):
        return resolve_cookies(self.cookies_key)

    def match(self, url):
        from ..validators import url_validator
        if url_validator.detect_platform(url) == self.platform_enum:
            return Match(url=url, validation=None)
        return None

    def scan(self, match):
        return gdl.enumerate(match.url, platform=self.name,
                             cookies=self._cookies(), extra_opts=self.gdl_opts)

    def download(self, url, dest_base):
        # Scan results are direct media URLs. Fetch them through the in-process
        # DNS-pinned client instead of handing an attacker-controlled CDN host to
        # a subprocess that would resolve and redirect independently.
        from ..netfetch import fetch_hardened_bytes
        allowed = {
            'image/jpeg', 'image/png', 'image/webp', 'image/gif', 'image/avif',
            'video/mp4', 'video/webm', 'video/quicktime',
        }
        ok, data, content_type, reason = fetch_hardened_bytes(
            url, allowed_types=allowed, max_bytes=200 * 1024 * 1024,
            require_image_magic=False)
        if not ok or data is None:
            return False, None, f'Échec du téléchargement {self.name} ({reason}).'
        extension_by_type = {
            'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp',
            'image/gif': '.gif', 'image/avif': '.avif', 'video/mp4': '.mp4',
            'video/webm': '.webm', 'video/quicktime': '.mov',
        }
        extension = extension_by_type.get(content_type)
        if not extension:
            extension = Path(urlparse(url).path).suffix.lower()[:10] or '.bin'
        destination = Path(f'{dest_base}{extension}')
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f'.{destination.name}.', suffix='.tmp', dir=destination.parent)
        try:
            with os.fdopen(descriptor, 'wb') as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            Path(temporary).unlink(missing_ok=True)
            raise
        return True, destination.name, None
