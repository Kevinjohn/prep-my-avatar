"""Validate mechanically checkable release and repository governance contracts."""
from __future__ import annotations

import argparse
import ast
import hashlib
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
VERSION_RE = re.compile(r"APP_VERSION\s*=\s*['\"]([^'\"]+)['\"]")
CANONICAL_REPOSITORY = "Kevinjohn/prep-my-avatar"
SCREENSHOT_MANIFEST = "docs/screenshots/manifest.yml"
ISSUE_CONTACT_ABOUT = (
    "Ask in #help for inherited LoRA Dataset Studio behavior; "
    "fork bugs and feature ideas belong in this repository's issues."
)


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def app_version() -> str:
    match = VERSION_RE.search(_read("backend/app/version.py"))
    if not match:
        raise ValueError("backend/app/version.py has no literal APP_VERSION")
    return match.group(1)


def validate_release(tag: str) -> list[str]:
    version = app_version()
    expected_tag = f"v{version}"
    errors: list[str] = []
    if tag != expected_tag:
        errors.append(f"tag {tag!r} does not match {expected_tag!r}")
    if f"current application release is **{version}**" not in _read("README.md"):
        errors.append(f"README.md does not identify {version} as the current release")
    changelog = _read("CHANGELOG.md")
    if not re.search(rf"^## {re.escape(version)}\s*$", changelog, re.MULTILINE):
        errors.append(f"CHANGELOG.md has no release heading for {version}")
    return errors


def validate_governance() -> list[str]:
    errors: list[str] = []
    catalog_tree = ast.parse(_read("backend/app/services/face_variations.py"))
    backend_labels = {
        node.args[3].value
        for node in ast.walk(catalog_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_e"
        and len(node.args) > 3
        and isinstance(node.args[3], ast.Constant)
        and isinstance(node.args[3].value, str)
    }
    frontend_labels = {
        key.replace("\\'", "'").replace("\\\\", "\\")
        for key in re.findall(
            r"^\s*'((?:[^'\\]|\\.)+)'\s*:",
            _read("frontend/src/utils/labels.js"), re.MULTILINE,
        )
    }
    missing_labels = sorted(backend_labels - frontend_labels)
    stale_labels = sorted(frontend_labels - backend_labels)
    if missing_labels:
        errors.append(f"frontend display labels missing backend catalog keys: {missing_labels}")
    if stale_labels:
        errors.append(f"frontend display labels contain stale backend keys: {stale_labels}")
    version = app_version()
    readme = _read("README.md")
    if f"**{version}**" not in readme:
        errors.append(f"README.md does not mention APP_VERSION {version}")
    changelog = _read("CHANGELOG.md")
    if not re.search(r"^## Unreleased\s*$", changelog, re.MULTILINE):
        errors.append("CHANGELOG.md has no Unreleased section")
    for relative in ("README.md", "CONTRIBUTING.md", "docs/VERSIONING.md"):
        text = _read(relative)
        if "prep-my-avatar" in text and CANONICAL_REPOSITORY not in text:
            errors.append(f"{relative} mentions the project without its canonical repository")
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), dict):
            errors.append(f"{path.relative_to(ROOT)} has no jobs mapping")
            continue
        if "concurrency" not in payload:
            errors.append(f"{path.relative_to(ROOT)} has no concurrency policy")
        for job_name, job in payload["jobs"].items():
            if not isinstance(job, dict) or "timeout-minutes" not in job:
                errors.append(f"{path.relative_to(ROOT)} job {job_name} has no timeout")
    for path in sorted((ROOT / ".github" / "ISSUE_TEMPLATE").glob("*.yml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if path.name == "config.yml":
            if not isinstance(payload, dict) or "blank_issues_enabled" not in payload:
                errors.append(f"{path.relative_to(ROOT)} is not a valid issue config")
            else:
                contact_links = payload.get("contact_links")
                about = (
                    contact_links[0].get("about")
                    if isinstance(contact_links, list)
                    and contact_links
                    and isinstance(contact_links[0], dict)
                    else None
                )
                if about != ISSUE_CONTACT_ABOUT:
                    errors.append(
                        f"{path.relative_to(ROOT)} does not preserve the complete "
                        "support contact description"
                    )
        elif not isinstance(payload, dict) or not isinstance(payload.get("body"), list):
            errors.append(f"{path.relative_to(ROOT)} has no issue-form body")
    link_re = re.compile(r"\[[^]]*\]\((?!https?://|mailto:|#)([^)]+)\)")
    markdown_paths = [ROOT / "README.md", ROOT / "CONTRIBUTING.md"]
    markdown_paths.extend(sorted((ROOT / "docs").rglob("*.md")))
    pull_request_template = ROOT / ".github/PULL_REQUEST_TEMPLATE.md"
    if pull_request_template.exists():
        markdown_paths.append(pull_request_template)
    for path in markdown_paths:
        relative = str(path.relative_to(ROOT))
        for target in link_re.findall(path.read_text(encoding="utf-8")):
            destination = (path.parent / target.split("#", 1)[0]).resolve()
            if not destination.exists():
                errors.append(f"{relative} links to missing path {target}")

    getting_started = _read("docs/guide/getting-started.md")
    install_target = (
        f"https://github.com/{CANONICAL_REPOSITORY}#installation-and-launch"
    )
    if install_target not in getting_started:
        errors.append("Getting started does not target the canonical Installation and launch section")
    if not re.search(r"^## Installation and launch\s*$", readme, re.MULTILINE):
        errors.append("README.md has no Installation and launch section")

    getting_help = _read("docs/guide/getting-help.md")
    if f"https://github.com/{CANONICAL_REPOSITORY}/issues" not in getting_help:
        errors.append("Getting help does not target the canonical issue tracker")
    if "perfectgf/lora-dataset-studio/issues" in getting_help:
        errors.append("Getting help routes fork reports to the upstream issue tracker")

    contributing = _read("CONTRIBUTING.md")
    if f"git clone https://github.com/{CANONICAL_REPOSITORY}.git" not in contributing:
        errors.append("Contributing guide does not clone the canonical repository")
    if "python -m pip install -e . -r backend/requirements-dev.txt" not in contributing:
        errors.append("Contributing guide does not install the root package for tests")

    pull_request = _read(".github/PULL_REQUEST_TEMPLATE.md")
    for command in (
        "python -m pytest backend/tests tests -q",
        "python -m ruff check backend src tests",
        "pnpm run gate",
    ):
        if command not in pull_request:
            errors.append(f"Pull request template omits canonical check: {command}")

    troubleshooting = _read("docs/guide/troubleshooting.md")
    if "provider console confirms the instance is terminated" not in troubleshooting:
        errors.append("Cloud troubleshooting omits provider-side billing confirmation")

    portable = _read("packaging/build_portable.ps1")
    if "(Join-Path $Root 'NOTICE.md') $Stage" not in portable:
        errors.append("Portable build does not stage NOTICE.md")

    implementation = _read("backend/app/services/face_dataset_service.py")
    match = re.search(
        r"recommendation_limit\s*=\s*\{'strict':\s*(\d+),\s*"
        r"'balanced':\s*(\d+),\s*'experimental':\s*(\d+)\}",
        implementation,
    )
    if not match:
        errors.append("Cannot identify coverage recommendation limits")
    else:
        limits = tuple(map(int, match.groups()))
        prose = _read("docs/specs/import-first-multi-reference-design.md")
        expected = re.compile(
            rf"at most\s+{limits[0]} proven catalogue gaps for strict,\s+"
            rf"{limits[1]} for balanced, and {limits[2]} for\s+experimental"
        )
        if not expected.search(prose):
            errors.append("Implemented-flow specification does not match coverage limits")

    errors.extend(_validate_screenshot_manifest(markdown_paths))
    return errors


def _validate_screenshot_manifest(markdown_paths: list[Path]) -> list[str]:
    errors: list[str] = []
    manifest_path = ROOT / SCREENSHOT_MANIFEST
    if not manifest_path.exists():
        return [f"{SCREENSHOT_MANIFEST} is missing"]
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    entries = payload.get("screenshots") if isinstance(payload, dict) else None
    if not isinstance(entries, list) or not entries:
        return [f"{SCREENSHOT_MANIFEST} has no screenshot records"]
    referenced = "\n".join(path.read_text(encoding="utf-8") for path in markdown_paths)
    required = {
        "path", "status", "capture_revision", "page", "viewport", "sha256",
        "owner", "relevant_sources",
    }
    manifested = {
        f"docs/screenshots/{entry.get('path')}"
        for entry in entries if isinstance(entry, dict) and entry.get('path')
    }
    screenshot_reference = re.compile(
        r"(?:\[[^]]*\]\(|<img[^>]+src=['\"])([^)'\"]*docs/screenshots/[^)'\"]+)"
    )
    for markdown_path in markdown_paths:
        for target in screenshot_reference.findall(
                markdown_path.read_text(encoding='utf-8')):
            target_path = target.split('#', 1)[0]
            try:
                normalized = str(
                    (markdown_path.parent / target_path).resolve().relative_to(ROOT)
                )
            except ValueError:
                normalized = target_path
            if normalized not in manifested:
                errors.append(
                    f"Referenced screenshot has no capture manifest: {normalized}")
    for entry in entries:
        if not isinstance(entry, dict) or not required <= entry.keys():
            errors.append("Screenshot record is missing capture metadata")
            continue
        relative = f"docs/screenshots/{entry['path']}"
        image_path = ROOT / relative
        if not image_path.is_file():
            errors.append(f"Screenshot record targets missing file {relative}")
            continue
        digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            errors.append(f"Screenshot digest changed without manifest update: {relative}")
        if not re.fullmatch(r"[0-9a-f]{40}", str(entry["capture_revision"])):
            errors.append(f"Screenshot has invalid capture revision: {relative}")
        if not re.fullmatch(r"[1-9]\d*x[1-9]\d*", str(entry["viewport"])):
            errors.append(f"Screenshot has invalid viewport: {relative}")
        if not isinstance(entry["owner"], str) or not entry["owner"].strip():
            errors.append(f"Screenshot has no owner: {relative}")
        relevant_sources = entry["relevant_sources"]
        if not isinstance(relevant_sources, list) or not relevant_sources:
            errors.append(f"Screenshot has no relevant source revisions: {relative}")
        else:
            for source in relevant_sources:
                if not isinstance(source, dict) or set(source) != {"path", "sha256"}:
                    errors.append(f"Screenshot has invalid relevant source metadata: {relative}")
                    continue
                source_path = ROOT / str(source["path"])
                if not source_path.is_file():
                    errors.append(
                        f"Screenshot relevant source is missing: {source['path']}"
                    )
                    continue
                source_digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
                if entry["status"] == "current" and source_digest != source["sha256"]:
                    errors.append(
                        f"Current screenshot predates relevant source: {relative} "
                        f"({source['path']})"
                    )
        if entry["status"] == "retired" and relative in referenced:
            errors.append(f"Retired screenshot is still referenced: {relative}")
        if entry["status"] not in {"current", "retired"}:
            errors.append(f"Screenshot has invalid status: {relative}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-tag")
    args = parser.parse_args()
    errors = validate_governance()
    if args.release_tag:
        errors.extend(validate_release(args.release_tag))
    for error in errors:
        print(f"repository contract error: {error}")
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
