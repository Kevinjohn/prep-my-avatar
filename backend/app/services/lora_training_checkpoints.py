"""Checkpoint discovery and deployment storage for local training."""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys

from . import face_dataset_service as fds
from . import lora_training as training
from .lora_training import (
    _LORA_ARCH_LABEL, _PERSISTED, _atomic_copy, _dest_base_tag,
    _output_dir, _run_name, _safe_trigger, _train_type,
    detect_lora_arch, lora_arch_conflicts,
)

logger = logging.getLogger(__name__)


def _trigger_boundary(name: str, prefix: str) -> bool:
    if not name.startswith(prefix):
        return False
    rest = name[len(prefix):]
    return rest == '' or rest[0] in '_.'

_CK_RE = re.compile(r'_(\d{4,})\.safetensors$')


def _run_dir(user_id, dataset_id, base_model=_PERSISTED, family=None) -> str:
    ds = fds.get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    # ai-toolkit écrit ses checkpoints/samples dans <training_folder>/<name>/
    # où name = 'lora_<trigger>' (cf. build_job_config). On pointe ce sous-dossier.
    # `base_model` cible le run d'une base PRÉCISE (sélection UI) ; `family` cible la
    # famille sélectionnée (Krea vs Z-Image) - sans quoi le panneau montre les
    # checkpoints du mauvais run quand deux familles partagent le même trigger.
    return str(_output_dir() / _run_name(ds, base_model, family) / f'lora_{_safe_trigger(ds)}')


def open_training_folder(user_id, dataset_id, target='loras', family=None,
                         base_model=_PERSISTED) -> str:
    """Ouvre dans l'explorateur de fichiers du POSTE (app locale mono-utilisateur,
    le navigateur tourne sur la même machine) le dossier demandé :
    'loras' → dossier d'import ComfyUI de la famille (loras/krea, loras/sdxl,
    loras/z image) ; 'run' → dossier de checkpoints du run courant (base+famille) ;
    'dataset' → projection d'entraînement gardée uniquement, matérialisée par
    « 💾 Write .txt files » (aucune dépendance ai-toolkit).
    Cibles FIXES résolues côté serveur — le client n'envoie jamais de chemin.
    Crée le dossier au besoin (avant un premier import il n'existe pas encore).
    Retourne le chemin ouvert."""
    ds = fds.get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    if target == 'run':
        path = _run_dir(user_id, dataset_id, base_model, family)
    elif target == 'loras':
        path = training._lora_dest_dir(ds, family)
    elif target == 'dataset':
        path = fds._training_projection_dir(dataset_id)
    else:
        raise ValueError('unknown folder target')
    os.makedirs(path, exist_ok=True)
    if os.name == 'nt':
        os.startfile(path)                                   # Explorateur Windows
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', path])
    else:
        subprocess.Popen(['xdg-open', path])
    logger.info('open folder (%s): %s', target, path)
    return path


def list_checkpoints(user_id, dataset_id, base_model=_PERSISTED, family=None) -> list[dict]:
    """Checkpoints .safetensors du run de la base+famille données (absentes → persistées),
    triés par step croissant. Retour: [{step:int, filename:str, final?:bool}].

    Inclut le fichier FINAL `lora_<trigger>.safetensors` (écrit à la fin d'un run
    abouti, SANS numéro de step) : c'est le résultat terminé, et le regex numéroté
    l'excluait → le LoRA fini était invisible/non importable depuis le panneau."""
    run = training._run_dir(user_id, dataset_id, base_model, family)
    if not os.path.isdir(run):
        return []
    out = []
    for f in os.listdir(run):
        m = _CK_RE.search(f)
        if m:
            out.append({'step': int(m.group(1)), 'filename': f})
    out.sort(key=lambda c: c['step'])
    # Fichier final (run = .../lora_<trigger> → lora_<trigger>.safetensors).
    final_name = os.path.basename(run) + '.safetensors'
    if os.path.isfile(os.path.join(run, final_name)):
        last = out[-1]['step'] if out else 0
        out.append({'step': last, 'filename': final_name, 'final': True})
    # Provenance annotation: which dataset VERSION most plausibly produced
    # each file (newest registry record older than the file). Pre-feature
    # datasets have no records -> no annotation, shape unchanged otherwise.
    from . import checkpoint_registry
    ds = fds.get_dataset(user_id, dataset_id)
    fam = _train_type(ds, family) if ds else None
    for c in out:
        try:
            rec = checkpoint_registry.record_for_mtime(
                dataset_id, fam, os.path.getmtime(os.path.join(run, c['filename'])))
        except OSError:
            rec = None
        if rec is not None:
            c['version'] = rec.version
            c['source'] = rec.source
            c['trained_at'] = rec.created_at.isoformat() if rec.created_at else None
    return out


def import_checkpoint(user_id, dataset_id, filename, base_model=_PERSISTED, family=None,
                      src_dir=None, version=None) -> str:
    """Copie le checkpoint choisi vers le dossier loras de ComfyUI : loras/z image/
    pour Z-Image, loras/sdxl/ pour SDXL, loras/krea/ pour Krea (routage par famille,
    pour ne pas polluer le Test Studio Z-Image). Anti path-traversal :
    le filename doit appartenir à la liste des checkpoints du run.

    Le nom de DESTINATION encode la base d'entraînement (_base_tag) : ai-toolkit
    écrit toujours `lora_<trigger>_<step>.safetensors` quel que soit le modèle de
    base (le `name` du job n'est pas base-aware), donc un LoRA entraîné sur un
    merge ComfyUI et un autre entraîné sur la base officielle produisent des
    fichiers IDENTIQUES qui, une fois copiés dans le dossier partagé de ComfyUI,
    sont indiscernables et s'écrasent au même step. On insère ici le tag du merge
    (`lora_<trigger>_<step>_<merge>.safetensors`) - la base officielle reste sans
    suffixe - pour les rendre reconnaissables ET éviter la collision. Le fichier
    source ai-toolkit n'est pas renommé (l'auto-resume continue de fonctionner).

    `base_model`/`family` ciblent le run d'une base+famille précises (sélection UI) ;
    absents → persistés. Run dir, whitelist, dossier ET suffixe de destination
    utilisent la MÊME base+famille → cohérent (un LoRA Krea part bien en loras/krea).

    `src_dir` (cloud seam) : le checkpoint est lu LÀ (dossier de staging où le pod a
    déposé le résultat téléchargé) au lieu du run ai-toolkit local - aucun besoin
    d'ai-toolkit configuré (ni _run_dir(), ni list_checkpoints(), qui appellent tous
    deux _output_dir()). La whitelist ici est PUREMENT anti-traversal : tout
    .safetensors réellement présent dans src_dir est autorisé (pas de filtre de
    forme _CK_RE — le checkpoint FINAL d'un run abouti, `lora_<trigger>.safetensors`,
    n'a pas de suffixe de step et doit passer). Défaut (None) = comportement
    historique inchangé."""
    ds = fds.get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    if src_dir:
        run_dir = str(src_dir)
        try:
            allowed = {f for f in os.listdir(run_dir)
                       if f.lower().endswith('.safetensors')}
        except OSError:
            allowed = set()
    else:
        run_dir = training._run_dir(user_id, dataset_id, base_model, family)
        allowed = {c['filename'] for c in training.list_checkpoints(
            user_id, dataset_id, base_model, family)}
    if filename not in allowed:
        raise ValueError('unknown checkpoint')
    # Arch guard: read the LoRA's REAL family from its header and refuse a deploy
    # that would land it in the wrong ComfyUI folder. ComfyUI silently drops every
    # incompatible key, so a Z-Image LoRA copied under loras/krea/ tests as a pure
    # no-op with no error anywhere (the 2026-07-13 incident). Undetectable header →
    # pass (no false block); only a POSITIVE cross-namespace mismatch stops here.
    fam_target = _train_type(ds, family)
    detected = detect_lora_arch(os.path.join(run_dir, filename))
    if lora_arch_conflicts(detected, fam_target):
        det_lbl = _LORA_ARCH_LABEL.get(detected, detected)
        tgt_lbl = _LORA_ARCH_LABEL.get(fam_target, fam_target)
        raise ValueError(
            f'this file is a {det_lbl} LoRA — deploy it under the {det_lbl} '
            f'family, not {tgt_lbl}.')
    # Déploiement routé par famille : sdxl → loras/sdxl, krea → loras/krea, sinon
    # « z image » (ne pollue pas le Test Studio Z-Image ; un LoRA Krea atterrit
    # directement dans le dossier lu par le menu de génération Krea).
    dest_dir = training._lora_dest_dir(ds, family)
    os.makedirs(dest_dir, exist_ok=True)
    tag = _dest_base_tag(ds, base_model, family)
    # Dataset-version suffix (_v3): makes successive dataset states
    # distinguishable in the ComfyUI/Test Studio dropdowns AND prevents a
    # cloud/local re-run of a CHANGED dataset from silently overwriting the
    # deployed LoRA of the previous version. `version` is passed explicitly by
    # the cloud import (the run knows its version); local imports resolve the
    # file's run via the provenance registry (file mtime vs launch times).
    # No registry rows (pre-feature datasets) -> no suffix, names unchanged.
    if version is None and not src_dir:
        from . import checkpoint_registry
        try:
            mtime = os.path.getmtime(os.path.join(run_dir, filename))
            rec = checkpoint_registry.record_for_mtime(
                dataset_id, _train_type(ds, family), mtime)
            version = rec.version if rec else None
        except OSError:
            version = None
    stem, ext = os.path.splitext(filename)
    # Cloud jobs are named `lds<run>_u<user>_<trigger>_<base>` on the pod, so
    # their checkpoints arrive as `lds12_ulocal_tata_cv_Krea-2-Raw_000000250`.
    # Deployed as-is, that stem is invisible to every trigger-prefix matcher
    # (Test Studio's `lora_<trigger>_…` whitelist, labels) — "my cloud
    # checkpoints are unusable", user-reported — and the deploy suffix used to
    # re-append a base tag the stem already carried. Normalize to the LOCAL
    # ai-toolkit convention at deploy time: `lora_<trigger>[_<step>]`, rebuilt
    # from the dataset's own trigger (no string surgery on the tag).
    if re.match(r'^lds\d+_u[0-9A-Za-z]+_', stem):
        step = re.search(r'_(\d{6,10})$', stem)
        stem = f'lora_{_safe_trigger(ds)}' + (f'_{step.group(1)}' if step else '')
    suffix = f'{tag}' + (f'_v{int(version)}' if version else '')
    dest_name = f'{stem}{suffix}{ext}' if suffix else filename
    dest = os.path.join(dest_dir, dest_name)
    _atomic_copy(os.path.join(run_dir, filename), dest)
    logger.info(f'import checkpoint {filename} -> {dest}')
    return dest


def list_imported_checkpoints(user_id, dataset_id, family=None) -> list[dict]:
    """LoRA de CE dataset déjà déployés dans le dossier loras de la FAMILLE demandée
    (chargeables par le Test Studio / la page generate). [{filename, label}].
    `family` (sélecteur UI) prime sur le train_type persisté : sans ça, la liste
    « IN COMFYUI (loras/…) » montrait toujours la famille persistée (ex. Krea) même
    quand l'utilisateur regardait la page Z-Image ou SDXL.

    Single-user app: no ownership DB to filter against (SRC's list_test_checkpoints
    consulted lora_ownership to hide LoRA belonging to OTHER users) -- everything on
    disk that matches this dataset's trigger boundary IS this dataset's checkpoint.
    A direct filesystem scan of the family's deploy folder replaces that call.
    `filename` is returned in LoraLoader form (family-subfolder\\name.safetensors),
    matching delete_imported_checkpoint's path resolution."""
    ds = fds.get_dataset(user_id, dataset_id)
    if not ds:
        return []
    fam = _train_type(ds, family)
    prefix = f'lora_{_safe_trigger(ds)}'
    try:
        dest_dir = training._lora_dest_dir(ds, family)
    except RuntimeError:
        return []
    if not os.path.isdir(dest_dir):
        return []
    from ..utils.comfyui import format_trained_lora_label
    # Cloud-trained checkpoints are auto-imported into the same folder but
    # named after the pod job (`lds<N>_<run>…`), not `lora_<trigger>…` — the
    # prefix filter alone hid them from the "IN COMFYUI" list even though the
    # files were right there (user-observed 2026-07-13). Accept any filename
    # that IS a known cloud checkpoint of THIS dataset.
    cloud_names = set()
    cloud_prefixes = set()
    try:
        from ..models import CloudTrainingRun
        for r in CloudTrainingRun.query.filter_by(dataset_id=dataset_id).all():
            if r.checkpoint_local_path:
                cloud_names.add(os.path.basename(r.checkpoint_local_path))
            # Every staging file of this run starts with its pod-job prefix
            # (`lds<id>_…`, see cloud_training job_name). Matching on the prefix
            # covers EVERY harvested epoch AND survives the `_<base_tag>` +
            # `_v<N>` suffixes import_checkpoint appends to the deployed name —
            # the exact-basename match above misses both (user-observed
            # 2026-07-13: imports succeeded but "in ComfyUI" stayed at 0).
            cloud_prefixes.add(f'lds{r.id}_')
    except Exception:
        pass
    subfolder = os.path.basename(os.path.normpath(dest_dir))
    out = []
    for fn in sorted(os.listdir(dest_dir)):
        if not fn.lower().endswith('.safetensors'):
            continue
        # deployed cloud names may carry the _v<N> dataset-version suffix —
        # strip it before matching against the staging basenames
        stem = re.sub(r'_v\d+(?=\.safetensors$)', '', fn)
        if not _trigger_boundary(fn, prefix) \
                and fn not in cloud_names and stem not in cloud_names \
                and not any(fn.startswith(p) for p in cloud_prefixes):
            continue
        entry = {'filename': os.path.join(subfolder, fn),
                 'label': format_trained_lora_label(fn, fam) or fn}
        # Retrofit signal for already-deployed files: if the header's real arch
        # contradicts THIS folder's family, flag it (mislabelled imports from the
        # pre-6952b11 wrong-arch bug) so the panel can badge it. No file is moved.
        detected = detect_lora_arch(os.path.join(dest_dir, fn))
        if lora_arch_conflicts(detected, fam):
            entry['arch_mismatch'] = detected
            entry['arch_label'] = _LORA_ARCH_LABEL.get(detected, detected)
        out.append(entry)
    return out


def delete_imported_checkpoint(user_id, dataset_id, filename, family=None) -> str:
    """Supprime un checkpoint déployé du dossier loras de ComfyUI. Garde-fous :
    le filename doit appartenir aux checkpoints importés du dataset (whitelist,
    famille-scopée) ET le chemin résolu doit rester dans le dossier loras de la
    FAMILLE sélectionnée (z image / sdxl / krea) - anti path-traversal, fail-closed.
    `family` (menu UI) prime sur le train_type persisté, comme la liste affichée."""
    ds = fds.get_dataset(user_id, dataset_id)
    allowed = {c['filename'] for c in list_imported_checkpoints(user_id, dataset_id, family=family)}
    if filename not in allowed:
        raise ValueError('unknown checkpoint')
    # ds is guaranteed truthy here: an unowned/missing dataset makes
    # list_imported_checkpoints return [] above, which already raised.
    root = os.path.abspath(training._lora_dest_dir(ds, family))
    loras_root = os.path.dirname(root)
    rel = filename.replace('\\', os.sep).replace('/', os.sep)
    dest = os.path.abspath(os.path.join(loras_root, rel))
    if os.path.commonpath([dest, root]) != root or not os.path.isfile(dest):
        raise ValueError('file not found')
    # trash, never destroy: a wrong click on a deployed LoRA is recoverable
    # until 'Empty trash' in Settings.
    from . import trash
    trash.send_to_trash(dest, context=f'lora_ds{dataset_id}')
    logger.info(f'trashed imported checkpoint {dest}')
    return os.path.basename(dest)
