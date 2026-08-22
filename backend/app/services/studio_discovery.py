"""Checkpoint and model discovery for the LoRA Test Studio.

This module owns filesystem/catalog discovery and family selection.  It has no
dependency on Studio launch, persistence, scoring, or payload assembly.
"""
from __future__ import annotations

import os

from .. import config as cfg
from ..models import FaceDataset
from ..utils.comfyui import (
    FAMILY_LABELS,
    format_trained_lora_label,
    get_checkpoint_models,
    get_krea_loras,
    get_sdxl_loras,
    get_zimage_loras,
)
from . import lora_training as training

FAMILIES = ("zimage", "sdxl", "krea")


def basename(path: str) -> str:
    return (path or "").replace("\\", "/").rsplit("/", 1)[-1]


def pool_for_family(family: str) -> list[dict]:
    family = (family or "zimage").lower()
    if family == "sdxl":
        return get_sdxl_loras()
    if family == "krea":
        return get_krea_loras()
    return get_zimage_loras()


def trigger_token_match(normalized_name: str, trigger: str) -> bool:
    if not normalized_name.startswith(trigger):
        return False
    remainder = normalized_name[len(trigger):]
    return remainder == "" or remainder[0] in ("_", "-")


def resolve_lora_path(checkpoint) -> str | None:
    """Resolve a loader-relative LoRA path without escaping the model root."""
    try:
        loras = cfg.comfyui_dir("loras")
    except Exception:
        loras = None
    if not loras:
        return None
    relative = str(checkpoint or "").replace("\\", os.sep).replace("/", os.sep)
    relative = relative.lstrip(os.sep)
    if not relative:
        return None
    root = os.path.realpath(str(loras))
    direct = os.path.realpath(os.path.join(root, relative))
    try:
        if os.path.commonpath((root, direct)) != root:
            return None
    except (OSError, ValueError):
        return None
    if os.path.isfile(direct):
        return direct
    current = root
    for part in relative.split(os.sep):
        if not part or part == ".":
            continue
        if part == "..":
            return None
        candidate = os.path.join(current, part)
        if os.path.exists(candidate):
            current = candidate
            continue
        try:
            match = next(
                (entry for entry in os.listdir(current) if entry.lower() == part.lower()),
                None,
            )
        except OSError:
            return None
        if match is None:
            return None
        current = os.path.join(current, match)
    return current if os.path.isfile(current) else None


def list_test_checkpoints(dataset, family=None) -> list[dict]:
    trigger = (dataset.trigger_word or "").strip().lower()
    if not trigger:
        return []
    family = (family or getattr(dataset, "train_type", None) or "zimage").lower()
    checkpoints = []
    for lora in pool_for_family(family):
        base = basename(lora["filename"])
        stem = base.rsplit(".", 1)[0]
        normalized = stem.lower()
        if normalized.startswith("lora_"):
            normalized = normalized[len("lora_"):]
        if not trigger_token_match(normalized, trigger):
            continue
        entry = {
            "filename": lora["filename"],
            "label": format_trained_lora_label(lora["filename"], family) or stem,
        }
        path = resolve_lora_path(lora["filename"])
        detected = training.detect_lora_arch(path) if path else None
        if training.lora_arch_conflicts(detected, family):
            entry["arch_mismatch"] = detected
            entry["arch_label"] = training._LORA_ARCH_LABEL.get(detected, detected)
        checkpoints.append(entry)
    return checkpoints


def _families_with_checkpoints(dataset) -> list[tuple[dict, list[dict]]]:
    """[(descripteur de famille, ses checkpoints)] pour les familles réellement
    entraînées sur ce dataset.

    Chaque `list_test_checkpoints` re-parcourt tout l'arbre loras/ : les appelants
    qui veulent LA LISTE et pas seulement le compte passent par ici plutôt que de
    relancer le scan famille par famille."""
    found = []
    for family in FAMILIES:
        checkpoints = list_test_checkpoints(dataset, family)
        if checkpoints:
            found.append(({
                "family": family,
                "label": FAMILY_LABELS.get(family, family),
                "count": len(checkpoints),
            }, checkpoints))
    return found


def available_families(dataset) -> list[dict]:
    return [descriptor for descriptor, _ in _families_with_checkpoints(dataset)]


def permanent_lora_candidates(family) -> list[dict]:
    candidates = []
    for lora in pool_for_family(family):
        base = basename(lora["filename"])
        if base.lower().startswith("lora_"):
            continue
        candidates.append({
            "filename": lora["filename"],
            "label": lora.get("displayName") or base.rsplit(".", 1)[0],
        })
    return candidates


def resolve_family(dataset, requested, families=None) -> str:
    families = available_families(dataset) if families is None else families
    keys = [item["family"] for item in families]
    requested = (requested or "").lower()
    if requested in keys:
        return requested
    default = (getattr(dataset, "train_type", None) or "zimage").lower()
    if default in keys:
        return default
    return keys[0] if keys else default


def list_sdxl_base_models() -> list[dict]:
    return [
        {"filename": model["name"], "label": basename(model["name"])}
        for model in get_checkpoint_models()
        if model.get("name")
    ]


def list_all_testable_checkpoints(user_id) -> list[dict]:
    result = []
    datasets = (
        FaceDataset.query.filter_by(user_id=str(user_id))
        .order_by(FaceDataset.id.asc())
        .all()
    )
    for dataset in datasets:
        for family, checkpoints in _families_with_checkpoints(dataset):
            result.append({
                "dataset_id": dataset.id,
                "dataset_name": dataset.name,
                "lora_label": dataset.trigger_word or dataset.name,
                "trigger_word": dataset.trigger_word,
                "family": family["family"],
                "family_label": family["label"],
                "train_type": family["family"],
                "checkpoints": checkpoints,
            })
    return result
