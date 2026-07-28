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
