# app/scrape/sources/gdl.py
"""Moteur gallery-dl réutilisable : énumération (--simulate -j) + classification
des codes de sortie. Générique (tag `platform` paramétrable) — hoist du wrapper
ad-hoc d'erome, avec la correction du sentinel d'erreur type -1 (auth/429/DDoS-
Guard étaient silencieusement lus comme « aucun média »).

Sécurité : --ignore-config, shell=False, args en liste, jamais --exec."""
import json
import os
import subprocess
import sys
import logging
import shutil
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

GDL_TIMEOUT = 60
SCAN_TIMEOUT = 60
DOWNLOAD_TIMEOUT = 300
DEFAULT_MAX_ITEMS = 120
DEFAULT_MAX_ALBUMS = 8
_VIDEO_EXTS = ('mp4', 'webm', 'mov', 'm4v')
_GENERIC_EXTRACTOR_DOMAINS = (
    'youtube.com', 'youtu.be', 'pornhub.com', 'xvideos.com', 'redgifs.com',
    'vimeo.com', 'dailymotion.com', 'x.com', 'twitter.com', 'tiktok.com',
    'coomer.st', 'coomer.su', 'coomer.party', 'coomer.cr',
    'kemono.cr', 'kemono.su', 'kemono.party',
    'cyberdrop.me', 'cyberdrop.cr', 'cyberdrop.to',
)

# Codes de sortie gallery-dl (bitmask, gallery_dl/exception.py) — vérifié sur 1.32.3.
EXIT_HTTP = 4
EXIT_NOTFOUND = 8
EXIT_AUTH = 16
EXIT_UNSUPPORTED = 64


def _subprocess_url_allowed(url):
    """Only recognized platform hosts may reach an extractor subprocess."""
    from ..validators import Platform, url_validator
    host = (urlparse(url).hostname or '').lower()
    if url_validator.detect_platform(url) != Platform.UNKNOWN:
        return True
    labels = host.split('.')
    if len(labels) >= 2 and labels[-2].startswith('bunkr'):
        return True
    return any(host == domain or host.endswith('.' + domain)
               for domain in _GENERIC_EXTRACTOR_DOMAINS)


def classify_exit(returncode):
    """Code de sortie gallery-dl → failure_kind ('unsupported'|'auth'|'network'|
    'toolerror') ou None si 0. Le bitmask est OR-combiné ; on teste du plus
    spécifique (unsupported) au plus générique."""
    if not returncode:
        return None
    if returncode & EXIT_UNSUPPORTED:
        return 'unsupported'
    if returncode & EXIT_AUTH:
        return 'auth'
    if returncode & (EXIT_NOTFOUND | EXIT_HTTP):
        return 'network'
    return 'toolerror'


def _media_item(entry, platform):
    """Entrée gallery-dl type 3 = [3, media_url, meta] → item schéma commun, ou None."""
    if not isinstance(entry, (list, tuple)) or len(entry) < 3:
        return None
    media_url = entry[1]
    meta = entry[2] if isinstance(entry[2], dict) else {}
    if not isinstance(media_url, str) or not media_url:
        return None
    ext = str(meta.get('extension', '')).lower()
    if not ext:
        ext = os.path.splitext(urlparse(media_url).path)[1].lstrip('.').lower()
    media_type = 'video' if ext in _VIDEO_EXTS else 'image'
    return {
        'url': media_url,
        'title': meta.get('title') or '',
        'thumbnail': meta.get('thumbnail') or (media_url if media_type == 'image' else None),
        'type': media_type,
        'platform': platform,
    }


def _run_simulate(url, max_items, cookies, extra_opts, image_range=None, timeout=None):
    """`gallery-dl --ignore-config --simulate -j` → (entries|None, error|None). Ne lève jamais.

    `image_range` (ex. '101-200') borne la FENÊTRE d'images du listing (image-range) ;
    défaut '1-{max_items}'. Sert la pagination « Charger plus » des sources à images
    directes (Civitai) où `--range` borne le flux (≠ pornpics qui empile des galeries
    → `--chapter-range` dans extra_opts)."""
    from ..netfetch import _validate_public_http_url
    valid, validation_error = _validate_public_http_url(url)
    if not valid:
        return None, validation_error or 'gallery-dl : URL réseau refusée.'
    if not _subprocess_url_allowed(url):
        return None, 'gallery-dl : hôte non autorisé pour un extracteur externe.'
    cmd = [sys.executable, '-m', 'gallery_dl', '--ignore-config',
           '--simulate', '-j', '--range', image_range or f'1-{max_items}']
    if cookies:
        cmd += ['--cookies', cookies]
    if extra_opts:
        cmd += list(extra_opts)
    cmd += ['--', url]
    try:
        effective_timeout = GDL_TIMEOUT if timeout is None else max(0.1, min(GDL_TIMEOUT, timeout))
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=effective_timeout, shell=False)
    except subprocess.TimeoutExpired:
        return None, f"gallery-dl : délai dépassé ({effective_timeout:.1f}s)."
    except Exception as e:
        logger.warning("gallery-dl: échec %s: %s", url, e)
        return None, f"gallery-dl : échec ({e})."

    stdout = (proc.stdout or '').strip()
    if not stdout:
        kind = classify_exit(proc.returncode)
        last = ((proc.stderr or '').strip().splitlines() or ['aucune donnée'])[-1]
        return None, f"gallery-dl : {kind or 'analyse vide'} ({last[:200]})."
    try:
        data = json.loads(stdout)
    except (ValueError, TypeError) as e:
        return None, f"gallery-dl : réponse illisible ({e})."
    if not isinstance(data, list):
        return None, "gallery-dl : format inattendu."
    kind = classify_exit(proc.returncode)
    if kind:
        last = ((proc.stderr or '').strip().splitlines() or ['échec extracteur'])[-1]
        return data, f"gallery-dl : résultats partiels, {kind} ({last[:200]})."
    return data, None


def _error_sentinel(entries):
    """Si une entrée type -1 (erreur d'extracteur) est présente, renvoie son message."""
    for entry in entries:
        if isinstance(entry, (list, tuple)) and entry and entry[0] == -1:
            meta = entry[1] if len(entry) > 1 and isinstance(entry[1], dict) else {}
            return (meta.get('message') or meta.get('error')
                    or "gallery-dl : l'extracteur a échoué.")
    return None


def enumerate(url, *, platform='generic', max_items=DEFAULT_MAX_ITEMS,
              max_albums=DEFAULT_MAX_ALBUMS, cookies=None, extra_opts=None,
              image_range=None, per_album=None):
    """Énumère les médias d'une URL via gallery-dl. Retourne (items, error).

    Gère les types de message : -1 (erreur → remontée), 2 (header, ignoré),
    3 (média), 6 (album enfant → récursion ≤ max_albums). Ne lève jamais.

    `image_range` borne la fenêtre d'images du listing TOP-LEVEL (pagination des
    sources à images directes) ; la récursion d'albums garde le défaut 1-max_items.

    `per_album` borne les images remontées PAR ALBUM lors de la récursion type 6
    (per_album=1 → la cover de chaque album, pas son contenu). Ne touche PAS les
    médias top-level : scanner l'URL d'un album précis rend toujours tout l'album."""
    try:
        deadline = time.monotonic() + SCAN_TIMEOUT
        entries, err = _run_simulate(url, max_items, cookies, extra_opts,
                                     image_range=image_range, timeout=SCAN_TIMEOUT)
        if err and not entries:
            return None, err
        top_error = err
        # CORRECTION clé : remonter le sentinel d'erreur type -1 (auth/429/DDoS-Guard)
        # AVANT de conclure « aucun média » (le bug d'origine d'erome).
        sentinel = _error_sentinel(entries)
        if sentinel:
            top_error = sentinel

        items = []
        seen_media = set()
        for entry in entries:
            if isinstance(entry, (list, tuple)) and entry and entry[0] == 3:
                item = _media_item(entry, platform)
                if item and item['url'] not in seen_media:
                    seen_media.add(item['url'])
                    items.append(item)
                    if len(items) >= max_items:
                        return items[:max_items], top_error
        if items:
            return items[:max_items], top_error
        if sentinel:
            return None, sentinel

        # Aucun média direct → récurser les albums (type 6).
        album_urls = []
        seen_albums = set()
        for entry in entries:
            if isinstance(entry, (list, tuple)) and len(entry) >= 2 and entry[0] == 6:
                if isinstance(entry[1], str) and entry[1] and entry[1] not in seen_albums:
                    seen_albums.add(entry[1])
                    album_urls.append(entry[1])
                    if len(album_urls) >= max_albums:
                        break
        album_errors = []
        for album_url in album_urls:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                album_errors.append('gallery-dl : délai global du scan dépassé.')
                break
            # per_album posé → borner la simulation elle-même (--range 1-N) : gallery-dl
            # s'arrête après N images au lieu d'énumérer tout l'album pour rien.
            sub, sub_err = _run_simulate(
                album_url, max_items, cookies, extra_opts,
                image_range=f'1-{per_album}' if per_album else None,
                timeout=remaining)
            if sub_err and not sub:
                album_errors.append(sub_err)
                continue
            if sub_err:
                album_errors.append(sub_err)
            if not sub:
                continue
            sent = _error_sentinel(sub)
            if sent:
                album_errors.append(sent)
                continue
            taken = 0
            for entry in sub:
                if isinstance(entry, (list, tuple)) and entry and entry[0] == 3:
                    item = _media_item(entry, platform)
                    if item and item['url'] not in seen_media:
                        seen_media.add(item['url'])
                        items.append(item)
                        taken += 1
                        if len(items) >= max_items:
                            return items[:max_items], (album_errors[0] if album_errors else top_error)
                        if per_album and taken >= per_album:
                            break
        if items:
            return items[:max_items], (album_errors[0] if album_errors else top_error)
        # Tous les albums ont échoué → remonter la 1ère erreur (auth/429) plutôt
        # qu'un faux « aucun média » (cas coomer/kemono derrière DDoS-Guard).
        if album_errors:
            return None, album_errors[0]
        return None, "gallery-dl : aucun média trouvé."
    except Exception as e:  # garde-fou ultime
        logger.exception("gdl.enumerate: erreur inattendue")
        return None, f"gallery-dl : erreur inattendue ({e})."


def download(url, dest_dir, filename, *, cookies=None, extra_opts=None):
    """Télécharge RÉELLEMENT via gallery-dl dans `dest_dir` avec un nom déterministe.
    Retourne (ok, abs_path|None, error|None). Ne lève jamais. Sécurité : --ignore-config,
    shell=False, args en liste, séparateur -- avant l'URL."""
    from ..netfetch import _validate_public_http_url
    valid, validation_error = _validate_public_http_url(url)
    if not valid:
        return False, None, validation_error or 'gallery-dl : URL réseau refusée.'
    if not _subprocess_url_allowed(url):
        return False, None, 'gallery-dl : hôte non autorisé pour un extracteur externe.'
    os.makedirs(dest_dir, exist_ok=True)
    staging = tempfile.mkdtemp(prefix='.gallery-dl-', dir=dest_dir)
    cmd = [sys.executable, '-m', 'gallery_dl', '--ignore-config',
           '-D', staging, '-o', f'filename={filename}_{{num}}.{{extension}}',
           '--no-part', '--no-mtime']
    if cookies:
        cmd += ['--cookies', cookies]
    if extra_opts:
        cmd += list(extra_opts)
    cmd += ['--', url]

    def cleanup_outputs():
        shutil.rmtree(staging, ignore_errors=True)

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=DOWNLOAD_TIMEOUT, shell=False)
    except subprocess.TimeoutExpired:
        cleanup_outputs()
        return False, None, "gallery-dl : téléchargement trop long (timeout)."
    except Exception as e:
        cleanup_outputs()
        logger.warning("gallery-dl download: échec %s: %s", url, e)
        return False, None, f"gallery-dl : échec ({e})."

    if proc.returncode:
        cleanup_outputs()
        kind = classify_exit(proc.returncode)
        last = ((proc.stderr or '').strip().splitlines() or [''])[-1]
        return False, None, f"gallery-dl : {kind or 'échec'} ({last[:200]})."

    # Chemin produit : 1) parser le stdout (gallery-dl imprime les chemins écrits) ;
    # 2) repli = le fichier le plus récent apparu dans dest_dir.
    root = Path(staging).resolve()

    def safe_output(candidate):
        path = Path(candidate)
        if not path.is_absolute():
            path = Path.cwd() / path
        if path.is_symlink():
            return None
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, ValueError):
            return None
        return resolved if resolved.is_file() else None

    for line in reversed((proc.stdout or '').splitlines()):
        line = line.strip()
        produced = safe_output(line) if line else None
        if produced is not None:
            final = Path(dest_dir).resolve() / produced.name
            os.replace(produced, final)
            cleanup_outputs()
            return True, str(final), None
    produced = [safe_output(path) for path in Path(staging).iterdir()]
    produced = [path for path in produced if path is not None]
    if produced:
        newest = max(produced, key=lambda path: path.stat().st_mtime)
        final = Path(dest_dir).resolve() / newest.name
        os.replace(newest, final)
        cleanup_outputs()
        return True, str(final), None
    cleanup_outputs()
    return False, None, "gallery-dl : aucun fichier produit."
