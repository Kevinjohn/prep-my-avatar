# app/scrape/sources/base.py
"""Interface commune des sources de scraping (registry pluggable).

DÉPENDANCE-FREE (abc/dataclasses/typing seulement) pour éviter tout cycle
d'import : les sources concrètes importent `validators` paresseusement dans
leur match(), jamais ce module."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import os
from pathlib import Path
import tempfile
from typing import Optional
from urllib.parse import urlparse


def atomic_write_bytes(destination, data: bytes) -> None:
    """Publish a complete download without exposing a partial final file."""
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        Path(temporary).unlink(missing_ok=True)
        raise


# Politique média des sources qui servent des photos et RIEN d'autre.
IMAGE_MEDIA_TYPES = frozenset({'image/jpeg', 'image/jpg', 'image/png',
                               'image/webp', 'image/gif'})
IMAGE_CT_EXT = {'image/jpeg': '.jpg', 'image/jpg': '.jpg', 'image/png': '.png',
                'image/webp': '.webp', 'image/gif': '.gif'}


def download_direct_media(url, dest_base, *, label,
                          allowed_types=IMAGE_MEDIA_TYPES, ct_ext=IMAGE_CT_EXT,
                          default_ext='.jpg'):
    """Fetch durci d'une URL média DIRECTE, publiée atomiquement. (ok, filename, error).

    `allowed_types` / `ct_ext` / `default_ext` sont des ARGUMENTS et non des
    constantes partagées : la politique média est un fait PAR SITE, pas une règle
    globale. Civitai accepte l'animation et devine `.png` (son CDN sert surtout du
    PNG) ; la base gallery-dl accepte la vidéo et devine `.bin`. Reddit et Sex.com
    sont la SEULE paire dont les trois valeurs coïncident — d'où les défauts
    ci-dessus. Unifier les autres ferait entrer un GIF ou un MP4 là où le site
    refuse délibérément les deux.

    `netfetch` est importé DANS le corps : ce module doit rester sans dépendance
    vers le reste de `scrape` (cf. docstring du module) pour éviter un cycle."""
    from ..netfetch import MAX_DRIVER_BYTES, fetch_hardened_bytes
    ok, data, ctype, reason = fetch_hardened_bytes(
        url, allowed_types=allowed_types, max_bytes=MAX_DRIVER_BYTES)
    if not ok or not data:
        return False, None, f'{label} : téléchargement échoué ({reason}).'
    ct = (ctype or '').split(';', 1)[0].strip().lower()
    ext = ct_ext.get(ct) or (os.path.splitext(urlparse(url).path)[1].lower() or default_ext)
    dest_dir = os.path.dirname(dest_base)
    filename = os.path.basename(dest_base) + ext
    try:
        atomic_write_bytes(os.path.join(dest_dir, filename), data)
    except OSError as e:
        return False, None, f"{label} : erreur d'écriture ({e})."
    return True, filename, None


@dataclass(frozen=True)
class Capabilities:
    """Déclare ce qu'une source sait faire. Lu par les appelants (routes /
    download_service) pour router sans connaître la source concrète."""
    can_enumerate_profile: bool = False         # profil/niche/album vs média unique
    needs_auth: bool = False                     # cookies requis (hint UX, pas un gate dur)
    media_kinds: frozenset = field(default_factory=lambda: frozenset({'video'}))
    own_downloader: bool = False                 # True=source.download() ; False=yt-dlp universel
    polite: bool = False                         # sleep/limit-rate (bunkr/cyberdrop/x)
    is_universal_fallback: bool = False          # exactement UNE source (priorité 0)


@dataclass
class Match:
    """Handle de résolution : l'URL + le ValidationResult parsé (ou None pour la
    source universelle) + la Source qui a matché (posée par le registry).

    `page` (0-based) est posé par la route /scan pour la pagination « Charger plus »
    des sources paginables (cf. Source.paginated) ; les autres sources l'ignorent —
    pas besoin de toucher leur signature scan()."""
    url: str
    validation: object = None
    source: object = None
    page: int = 0
    # True asks album-capable image sources to enumerate album contents rather
    # than returning cover images only. Other sources intentionally ignore it.
    include_albums: bool = False


class Source(ABC):
    """Une source de scraping. `match(url)` renvoie un Match si l'URL la concerne,
    sinon None. `scan(match)` énumère les médias. `download(url, dest_base)` n'est
    appelé QUE si capabilities.own_downloader (sinon l'appelant passe par yt-dlp)."""
    name: str = 'source'
    priority: int = 0
    capabilities: Capabilities = Capabilities()
    paginated: bool = False   # scan() honore match.page → la route expose « Charger plus »
    # Catégorie d'accès : 'image' = ouvert aux non-admins (avec la feature scrape),
    # 'video' = RÉSERVÉ à l'admin (scan ET download refusés aux non-admins). Défaut
    # 'video' = fail-closed : une nouvelle source est admin-only tant qu'on ne la classe
    # pas explicitement 'image'.
    category: str = 'video'

    @abstractmethod
    def match(self, url: str) -> Optional[Match]:
        ...

    @abstractmethod
    def scan(self, match: Match) -> tuple[list, Optional[str]]:
        """Retourne (items, diagnostic). Un diagnostic avec des items signifie
        résultat partiel ; sans items, il signifie échec total. Ne lève jamais."""
        ...

    def download(self, url: str, dest_base: str) -> tuple[bool, Optional[str], Optional[str]]:
        """Retourne (ok: bool, filename: str|None, error: str|None).
        Défaut : non supporté (les sources own_downloader=False passent par yt-dlp)."""
        raise NotImplementedError(f"{self.name} n'a pas de downloader dédié")
