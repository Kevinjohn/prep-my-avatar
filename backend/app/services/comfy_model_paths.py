"""Canonical ComfyUI model search, listing, and resolution paths."""

from __future__ import annotations

import logging
import ntpath
import os
import threading

from .. import config as cfg

logger = logging.getLogger(__name__)

try:
    import yaml as _yaml
except ImportError:  # Existing installations may update without reinstalling requirements.
    _yaml = None


YAML_FILENAME = "extra_model_paths.yaml"
MODEL_EXTENSIONS = frozenset(
    {".ckpt", ".pt", ".pt2", ".bin", ".pth", ".safetensors", ".pkl", ".sft"}
)

_ALIASES = {"unet": "diffusion_models", "clip": "text_encoders"}
_DEFAULT_SUBDIRS = {
    "checkpoints": ("checkpoints",),
    "loras": ("loras",),
    "vae": ("vae",),
    "text_encoders": ("text_encoders", "clip"),
    "diffusion_models": ("unet", "diffusion_models"),
}

_cache_lock = threading.Lock()
_cache_key = None
_cache_data: dict[str, list[tuple[str, bool]]] = {}


def _canonical_type(folder_type: str) -> str:
    name = str(folder_type or "")
    return _ALIASES.get(name, name)


def _models_root() -> str | None:
    try:
        root = cfg.comfyui_dir("models")
    except (KeyError, TypeError, ValueError):
        return None
    return os.path.normpath(str(root)) if root else None


def _default_roots(folder_type: str) -> list[str]:
    if folder_type == "loras":
        try:
            loras = cfg.comfyui_dir("loras")
        except (KeyError, TypeError, ValueError):
            loras = None
        return [os.path.normpath(str(loras))] if loras else []

    models = _models_root()
    if not models:
        return []
    subdirs = _DEFAULT_SUBDIRS.get(folder_type, (folder_type,))
    return [os.path.normpath(os.path.join(models, subdir)) for subdir in subdirs]


def _yaml_path() -> str | None:
    try:
        base = str(cfg.get("comfyui.base_dir") or "").strip()
    except (KeyError, TypeError, ValueError):
        return None
    return os.path.join(base, YAML_FILENAME) if base else None


def _parse_yaml(path: str) -> dict[str, list[tuple[str, bool]]]:
    if _yaml is None:
        return {}
    try:
        with open(path, encoding="utf-8-sig") as stream:
            config = _yaml.safe_load(stream)
    except (OSError, _yaml.YAMLError) as exc:
        logger.warning("Ignoring invalid %s: %s", YAML_FILENAME, exc)
        return {}

    if config is None:
        return {}
    if not isinstance(config, dict):
        logger.warning("Ignoring %s because its top level is not a mapping", YAML_FILENAME)
        return {}

    yaml_dir = os.path.dirname(os.path.abspath(path))
    parsed: dict[str, list[tuple[str, bool]]] = {}
    for profile in config.values():
        if profile is None:
            continue
        if not isinstance(profile, dict):
            logger.warning("Ignoring %s because a profile is not a mapping", YAML_FILENAME)
            return {}
        profile = dict(profile)
        base_path = profile.pop("base_path", None)
        if base_path is not None:
            base_path = os.path.expandvars(os.path.expanduser(str(base_path)))
            if not os.path.isabs(base_path):
                base_path = os.path.abspath(os.path.join(yaml_dir, base_path))
        is_default = bool(profile.pop("is_default", False))
        for raw_type, raw_paths in profile.items():
            if raw_paths is None:
                continue
            if not isinstance(raw_paths, str):
                logger.warning("Ignoring %s because a folder path is not text", YAML_FILENAME)
                return {}
            folder_type = _canonical_type(raw_type)
            for value in raw_paths.split("\n"):
                if not value:
                    continue
                full_path = os.path.join(base_path, value) if base_path else value
                if not os.path.isabs(full_path):
                    full_path = os.path.abspath(os.path.join(yaml_dir, full_path))
                parsed.setdefault(folder_type, []).append(
                    (os.path.normpath(full_path), is_default)
                )
    return parsed


def _extra_config() -> dict[str, list[tuple[str, bool]]]:
    global _cache_key, _cache_data

    path = _yaml_path()
    if not path or _yaml is None:
        return {}
    try:
        stat = os.stat(path)
    except OSError:
        return {}
    key = (path, stat.st_mtime_ns, stat.st_size)
    with _cache_lock:
        if _cache_key == key:
            return _cache_data

    parsed = _parse_yaml(path)
    with _cache_lock:
        _cache_key = key
        _cache_data = parsed
    return parsed


def clear_cache() -> None:
    """Clear cached YAML data; production refreshes automatically by file metadata."""
    global _cache_key, _cache_data

    with _cache_lock:
        _cache_key = None
        _cache_data = {}


def search_roots(folder_type: str) -> list[str]:
    """Return default and extra roots in the order ComfyUI searches them."""
    canonical = _canonical_type(folder_type)
    roots = _default_roots(canonical)
    for path, is_default in _extra_config().get(canonical, []):
        if path in roots:
            if is_default and roots[0] != path:
                roots.remove(path)
                roots.insert(0, path)
        elif is_default:
            roots.insert(0, path)
        else:
            roots.append(path)
    return roots


def write_root(folder_type: str) -> str | None:
    """Return the single highest-priority root to receive new model files."""
    canonical = _canonical_type(folder_type)
    if canonical == "loras":
        try:
            explicit = str(cfg.get("comfyui.loras_dir") or "").strip()
        except (KeyError, TypeError, ValueError):
            explicit = ""
        if explicit:
            return os.path.normpath(explicit)
    roots = search_roots(canonical)
    return roots[0] if roots else None


def _is_contained(root: str, candidate: str) -> bool:
    real_root = os.path.realpath(root)
    real_candidate = os.path.realpath(candidate)
    try:
        return os.path.commonpath((real_root, real_candidate)) == real_root
    except (OSError, ValueError):
        return False


def _iter_models(root: str):
    if not os.path.isdir(root):
        return
    visited: set[str] = set()
    for directory, subdirs, filenames in os.walk(root, followlinks=True, topdown=True):
        real_directory = os.path.realpath(directory)
        if real_directory in visited or not _is_contained(root, directory):
            subdirs.clear()
            continue
        visited.add(real_directory)
        subdirs[:] = [
            name
            for name in subdirs
            if name != ".git" and _is_contained(root, os.path.join(directory, name))
        ]
        for filename in filenames:
            if os.path.splitext(filename)[1].lower() not in MODEL_EXTENSIONS:
                continue
            absolute = os.path.join(directory, filename)
            if not _is_contained(root, absolute) or not os.path.isfile(absolute):
                continue
            yield os.path.relpath(absolute, root), absolute


def list_models(folder_type: str) -> list[tuple[str, str]]:
    """Return unique ``(loader-relative name, absolute path)`` model entries."""
    seen: set[str] = set()
    models: list[tuple[str, str]] = []
    for root in search_roots(folder_type):
        entries = sorted(_iter_models(root), key=lambda entry: entry[0].lower())
        for relative, absolute in entries:
            if relative in seen:
                continue
            seen.add(relative)
            models.append((relative, absolute))
    return models


def _case_insensitive_file(root: str, relative: str) -> str | None:
    if not os.path.isdir(root):
        return None
    current = root
    for part in relative.split(os.sep):
        if not part or part == ".":
            continue
        try:
            entries = os.listdir(current)
        except OSError:
            return None
        match = part if part in entries else next(
            (name for name in entries if name.lower() == part.lower()),
            None,
        )
        if match is None:
            return None
        current = os.path.join(current, match)
        if not _is_contained(root, current):
            return None
    return current if os.path.isfile(current) else None


def resolve_model_file(folder_type: str, ref: str) -> str | None:
    """Resolve a loader-relative model reference without leaving a search root."""
    raw_ref = str(ref or "")
    slash_ref = raw_ref.replace("\\", "/")
    if (
        not raw_ref
        or os.path.isabs(raw_ref)
        or ntpath.isabs(raw_ref)
        or ".." in slash_ref.split("/")
    ):
        return None
    relative = slash_ref.replace("/", os.sep).strip(os.sep)
    if not relative:
        return None

    for root in search_roots(folder_type):
        resolved = _case_insensitive_file(root, relative)
        if resolved:
            return resolved
    return None
