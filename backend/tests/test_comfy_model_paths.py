"""Contract tests for canonical ComfyUI model-root resolution."""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _reset_path_cache():
    from app.services import comfy_model_paths

    comfy_model_paths.clear_cache()
    yield
    comfy_model_paths.clear_cache()


def _configure_comfyui(app, tmp_path, *, loras_dir="") -> Path:
    from app import config

    base = tmp_path / "ComfyUI"
    (base / "models").mkdir(parents=True)
    with app.app_context():
        config.save_config(
            {
                "comfyui": {
                    "base_dir": str(base),
                    "loras_dir": str(loras_dir) if loras_dir else "",
                }
            }
        )
    return base


def _write_extra_paths(base: Path, contents: str) -> Path:
    path = base / "extra_model_paths.yaml"
    path.write_text(textwrap.dedent(contents), encoding="utf-8")
    return path


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"model")
    return path


def test_default_roots_and_legacy_aliases_match_comfyui(app, tmp_path):
    from app.services import comfy_model_paths

    base = _configure_comfyui(app, tmp_path)

    assert comfy_model_paths.search_roots("checkpoints") == [
        str(base / "models" / "checkpoints")
    ]
    assert comfy_model_paths.search_roots("unet") == [
        str(base / "models" / "unet"),
        str(base / "models" / "diffusion_models"),
    ]
    assert comfy_model_paths.search_roots("clip") == [
        str(base / "models" / "text_encoders"),
        str(base / "models" / "clip"),
    ]


def test_extra_paths_support_profiles_relative_base_multiline_and_priority(
    app, tmp_path, monkeypatch
):
    from app.services import comfy_model_paths

    base = _configure_comfyui(app, tmp_path)
    env_root = tmp_path / "shared"
    monkeypatch.setenv("COMFY_TEST_ROOT", str(env_root))
    preferred = tmp_path / "preferred"
    secondary = tmp_path / "secondary"
    _write_extra_paths(
        base,
        f"""
        shared:
          base_path: $COMFY_TEST_ROOT
          diffusion_models: |
            unet
            diffusion_models
          clip: text
        preferred:
          is_default: true
          unet: {preferred}
        duplicate:
          diffusion_models: {preferred}
        secondary:
          diffusion_models: {secondary}
        """,
    )

    assert comfy_model_paths.search_roots("diffusion_models") == [
        str(preferred),
        str(base / "models" / "unet"),
        str(base / "models" / "diffusion_models"),
        str(env_root / "unet"),
        str(env_root / "diffusion_models"),
        str(secondary),
    ]
    assert comfy_model_paths.search_roots("text_encoders")[-1] == str(env_root / "text")


def test_relative_base_path_resolves_from_yaml_directory(app, tmp_path):
    from app.services import comfy_model_paths

    base = _configure_comfyui(app, tmp_path)
    _write_extra_paths(
        base,
        """
        portable:
          base_path: shared
          vae: models/vae
        """,
    )

    assert comfy_model_paths.search_roots("vae")[-1] == str(
        base / "shared" / "models" / "vae"
    )


def test_missing_malformed_or_unavailable_yaml_degrades_to_defaults(
    app, tmp_path, monkeypatch
):
    from app.services import comfy_model_paths

    base = _configure_comfyui(app, tmp_path)
    default = [str(base / "models" / "loras")]
    assert comfy_model_paths.search_roots("loras") == default

    _write_extra_paths(base, "profile: [unterminated\n")
    assert comfy_model_paths.search_roots("loras") == default

    monkeypatch.setattr(comfy_model_paths, "_yaml", None)
    comfy_model_paths.clear_cache()
    assert comfy_model_paths.search_roots("loras") == default


def test_cache_refreshes_when_yaml_mtime_changes(app, tmp_path):
    from app.services import comfy_model_paths

    base = _configure_comfyui(app, tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"
    yaml_path = _write_extra_paths(base, f"profile:\n  vae: {first}\n")
    assert comfy_model_paths.search_roots("vae")[-1] == str(first)

    yaml_path.write_text(f"profile:\n  vae: {second}\n", encoding="utf-8")
    stat = yaml_path.stat()
    os.utime(yaml_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    assert comfy_model_paths.search_roots("vae")[-1] == str(second)


def test_list_and_resolve_models_use_loader_names_and_root_priority(app, tmp_path):
    from app.services import comfy_model_paths

    base = _configure_comfyui(app, tmp_path)
    primary = tmp_path / "primary"
    secondary = tmp_path / "secondary"
    primary_model = _touch(primary / "Klein" / "shared.safetensors")
    _touch(secondary / "Klein" / "shared.safetensors")
    unique_model = _touch(secondary / "nested" / "unique.sft")
    _touch(secondary / "nested" / "ignored.txt")
    _write_extra_paths(
        base,
        f"""
        primary:
          is_default: true
          diffusion_models: {primary}
        secondary:
          diffusion_models: {secondary}
        """,
    )

    models = dict(comfy_model_paths.list_models("unet"))
    loader_name = os.path.join("Klein", "shared.safetensors")
    assert models[loader_name] == str(primary_model)
    assert models[os.path.join("nested", "unique.sft")] == str(unique_model)
    assert not any(name.endswith("ignored.txt") for name in models)
    assert comfy_model_paths.resolve_model_file("unet", loader_name) == str(primary_model)
    assert comfy_model_paths.resolve_model_file("unet", "klein/SHARED.safetensors") == str(
        primary_model
    )


def test_absolute_traversal_and_symlink_escapes_fail_closed(app, tmp_path):
    from app.services import comfy_model_paths

    base = _configure_comfyui(app, tmp_path)
    root = base / "models" / "checkpoints"
    root.mkdir(parents=True)
    outside = _touch(tmp_path / "outside" / "secret.safetensors")
    link = root / "linked"
    try:
        link.symlink_to(outside.parent, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks are unavailable on this platform")

    assert comfy_model_paths.resolve_model_file("checkpoints", str(outside)) is None
    assert comfy_model_paths.resolve_model_file("checkpoints", "../outside/secret.safetensors") is None
    assert comfy_model_paths.resolve_model_file("checkpoints", "linked/secret.safetensors") is None
    assert not any("secret.safetensors" in name for name, _ in comfy_model_paths.list_models("checkpoints"))


def test_write_root_honours_explicit_override_then_comfyui_priority(app, tmp_path):
    from app.services import comfy_model_paths

    explicit = tmp_path / "explicit-loras"
    base = _configure_comfyui(app, tmp_path, loras_dir=explicit)
    yaml_default = tmp_path / "yaml-default"
    _write_extra_paths(
        base,
        f"""
        preferred:
          is_default: true
          loras: {yaml_default}
        """,
    )
    assert comfy_model_paths.write_root("loras") == str(explicit)

    from app import config

    with app.app_context():
        config.save_config({"comfyui": {"loras_dir": ""}})
    assert comfy_model_paths.write_root("loras") == str(yaml_default)
