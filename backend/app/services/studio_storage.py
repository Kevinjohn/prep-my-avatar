"""Crash-safe Studio output publication and orphan retention."""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Protocol

from ..extensions import db
from ..models import LoraTestImage
from . import face_dataset_service as fds

logger = logging.getLogger(__name__)


class StorageRuntime(Protocol):
    def comfy_output_dir(self): ...


# --- Completion linking (called from job_queue) --------------------------------
def cleanup_output_file(runtime, filename, failed):
    """Move an orphaned completed output to recoverable Trash, best-effort."""
    if (failed or not filename or not isinstance(filename, str)
            or Path(filename).name != filename or filename in ('.', '..')):
        return
    out_dir = runtime.comfy_output_dir()
    if not out_dir:
        return
    try:
        p = os.path.join(out_dir, filename)
        if os.path.isfile(p):
            from . import trash
            trash.send_paths_to_trash(
                [p], context='orphaned-studio-output', metadata={
                    'kind': 'orphaned_generation',
                    'label': f'Orphaned Studio output: {os.path.basename(filename)}',
                })
    except (OSError, ValueError):
        logger.exception('could not retain orphaned Studio output %s', filename)


def reserve_dataset_output(dataset_id, filename, row_id):
    """Atomically claim a dataset-local output name without overwriting bytes."""
    root = Path(fds._dataset_dir(dataset_id))
    digest = hashlib.sha256(filename.encode('utf-8')).hexdigest()[:12]
    suffix = Path(filename).suffix[:16]
    candidates = [filename]
    candidates.extend(
        f'studio-{row_id}-{digest}{"" if index == 1 else f"-{index}"}{suffix}'
        for index in range(1, 1001))
    for candidate in candidates:
        path = root / candidate
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            continue
        os.close(fd)
        return candidate, path
    raise OSError('could not allocate a collision-free Studio output filename')


def copy_output_into_reservation(source: Path, destination: Path) -> None:
    """Copy across volumes atomically while retaining the source until DB commit."""
    temporary = destination.with_name(
        f'.{destination.name}.part-{uuid.uuid4().hex}')
    try:
        shutil.copy2(source, temporary, follow_symlinks=False)
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def link_completed_test_image(runtime, job_id, filename, failed=False, reason=None):
    """Attach a finished studio job to its LoraTestImage row.

    Mirror of link_completed_dataset_image: runs in the queue monitor thread
    whose SQLAlchemy session may hold a STALE read snapshot - if the first
    lookup misses, rollback (end the transaction) and re-read on a fresh
    snapshot before concluding the row doesn't exist.
    `reason` (the job row's error_message: a ComfyUI 400 validation body / node
    execution error / timeout) is persisted on the failed cell so the tile can
    say WHY it's empty instead of a mute red square (P0-b)."""
    if filename and (not isinstance(filename, str)
                     or Path(filename).name != filename
                     or filename in ('.', '..')):
        failed = True
        reason = 'ComfyUI returned an unsafe output filename'
        filename = None
    img = LoraTestImage.query.filter_by(job_id=job_id).first()
    if img is None:
        db.session.rollback()  # drop the stale read snapshot, then re-read
        img = LoraTestImage.query.filter_by(job_id=job_id).first()
    if img is None:
        logger.warning(f"lora-test link: no LoraTestImage row for job {job_id}")
        cleanup_output_file(runtime, filename, failed)  # job sans ligne (annulé/repris) → orphelin
        return
    # Ne finaliser que les cellules ENCORE en attente : une complétion tardive d'un
    # job dont la ligne a été annulée/reprise (nouveau job_id, statut ≠ pending) ne
    # doit pas écraser le bon run - on jette son fichier au lieu de le déplacer.
    if not failed and img.status != 'pending':
        logger.info(f"lora-test link: ligne {img.id} déjà {img.status} pour job {job_id} - ignoré")
        cleanup_output_file(runtime, filename, failed)
        return
    retained_source = None
    retained_destination = None
    if failed:
        img.status = 'failed'
        img.error = (reason
                     or 'Generation failed (see 🪵 Server log in Settings for the ComfyUI error).')
    else:
        # Bring the completed file into the per-dataset dir (served by
        # /api/dataset/<id>/img/<filename>, cleaned with the dataset). Prefer a
        # local disk move from ComfyUI's output dir; if the file isn't there —
        # ComfyUI was pointed at a custom output path, or none is configured —
        # fetch it over the /view API instead (path-independent). See GH #2.
        local_name, dst = reserve_dataset_output(img.dataset_id, filename, img.id)
        out_dir = runtime.comfy_output_dir()
        src = Path(out_dir) / filename if out_dir else None
        try:
            if src and src.is_file() and not src.is_symlink():
                copy_output_into_reservation(src, dst)
                retained_source = src
                available = True
            else:
                from ..utils.comfyui import fetch_output_image_bytes
                data = fetch_output_image_bytes(filename)
                available = bool(data)
                if available:
                    fds._atomic_write_bytes(dst, data)
            if available:
                retained_destination = dst
                img.filename = local_name
                img.status = 'done'
                img.error = None
            else:
                # The result vanished (not on disk, /view fetch failed) — mark the
                # cell failed WITH a reason rather than leaving a 'done' row whose
                # <img> would 404 into a mute broken tile (P0-b, mirrors the dataset
                # fan-out's fail path).
                dst.unlink(missing_ok=True)
                img.filename = None
                img.status = 'failed'
                img.error = ('The finished image could not be retrieved from ComfyUI '
                             '(not on disk, and the /view API fetch failed).')
                logger.warning(f"lora-test link: file not on disk and /view API fetch failed for {filename}")
        except Exception as exc:
            try:
                dst.unlink(missing_ok=True)
            except OSError:
                pass
            img.filename = None
            img.status = 'failed'
            img.error = f'Could not retain the finished Studio image: {exc}'[:400]
            logger.exception('lora-test link: could not retain output %s', filename)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        if retained_destination is not None:
            try:
                retained_destination.unlink(missing_ok=True)
            except OSError:
                logger.exception('could not remove uncommitted Studio output %s',
                                 retained_destination)
        raise
    if retained_source is not None:
        try:
            retained_source.unlink()
        except OSError:
            logger.warning('Studio output linked but source cleanup failed: %s',
                           retained_source)
