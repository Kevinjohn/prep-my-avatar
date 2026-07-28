"""Studio rating, analytics, feedback, and objective face scoring."""
from __future__ import annotations

import json
import logging
import math
import os
import re

from ..extensions import db
from ..models import LoraTestImage, TrainingRunRecord
from ..utils.comfyui import (
    family_of_lora,
    format_trained_lora_label,
    get_krea_models,
    get_zimage_models,
)
from ..utils.time import utcfromtimestamp, utcnow
from . import face_dataset_service as fds
from . import studio_discovery as discovery

logger = logging.getLogger(__name__)
_basename = discovery.basename
_resolve_lora_abs_path = discovery.resolve_lora_path
list_test_checkpoints = discovery.list_test_checkpoints
list_sdxl_base_models = discovery.list_sdxl_base_models
_resolve_family = discovery.resolve_family
available_families = discovery.available_families
TEST_ASPECTS = {'9:16', '3:4', '1:1', '4:3', '16:9'}


def _wilson_lower_bound(likes: int, voted: int, z: float = 1.96) -> float:
    if voted <= 0:
        return 0.0
    p = likes / voted
    z2 = z * z
    denominator = 1.0 + z2 / voted
    center = p + z2 / (2 * voted)
    margin = z * math.sqrt((p * (1 - p) + z2 / (4 * voted)) / voted)
    return (center - margin) / denominator


# --- Rating + best settings ---------------------------------------------------
def _owned_test_image(user_id, image_id):
    """Single-user app: no cross-user ownership check (SRC compared the
    image's dataset.user_id against `user_id`) - just the row lookup."""
    return db.session.get(LoraTestImage, image_id)


def rate_image(user_id, image_id, rating) -> bool:
    if rating not in (1, -1, 0):
        return False
    img = _owned_test_image(user_id, image_id)
    if not img:
        return False
    img.rating = rating
    db.session.commit()
    return True


def _model_label(z_model):
    return _basename(z_model).rsplit('.', 1)[0] if z_model else None


_DATASET_VERSION_RE = re.compile(r'_v(\d+)(?=(?:_|\.|$))', re.IGNORECASE)
_CHECKPOINT_STEP_RE = re.compile(r'_(\d{4,})(?=(?:_|\.|$))')


def _checkpoint_version(checkpoint):
    """Dataset version encoded by deployed checkpoint naming, if present."""
    matches = _DATASET_VERSION_RE.findall(_basename(checkpoint or ''))
    return int(matches[-1]) if matches else None


def _checkpoint_step(checkpoint):
    """Training step encoded by an intermediate checkpoint, if present."""
    matches = _CHECKPOINT_STEP_RE.findall(_basename(checkpoint or ''))
    return int(matches[-1]) if matches else None


def _json_object(value):
    try:
        parsed = json.loads(value or '{}')
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _record_for_checkpoint(dataset_id, family, checkpoint, records=None,
                           explicit_id=None):
    """Resolve a deployed LoRA to the launch that produced it.

    New Studio rows carry an explicit immutable record id.  For historical
    rows, the deployed file preserves the source checkpoint mtime and its name
    usually carries ``_vN``; both signals are used together.  Ambiguous rows
    remain unlinked instead of being attributed to a convenient latest run.
    """
    family = (family or family_of_lora(checkpoint) or 'zimage').lower()
    candidates = list(records) if records is not None else (
        TrainingRunRecord.query
        .filter_by(dataset_id=dataset_id, family=family)
        .order_by(TrainingRunRecord.created_at.desc(),
                  TrainingRunRecord.id.desc()).all())
    candidates = [r for r in candidates
                  if r.dataset_id == dataset_id and r.family == family]
    if explicit_id:
        linked = next((r for r in candidates if r.id == explicit_id), None)
        if linked is not None:
            return linked

    version = _checkpoint_version(checkpoint)
    if version is not None:
        candidates = [r for r in candidates if r.version == version]
    if not candidates:
        return None

    try:
        path = _resolve_lora_abs_path(checkpoint)
        written_at = utcfromtimestamp(os.path.getmtime(path)) if path else None
    except (OSError, OverflowError, ValueError):
        written_at = None
    if written_at is not None:
        eligible = [r for r in candidates
                    if r.created_at is not None and r.created_at <= written_at]
        if eligible:
            return max(eligible, key=lambda r: (r.created_at, r.id))
    # A version suffix is an explicit provenance signal.  If several launches
    # reused the exact same dataset version and no usable mtime exists, prefer
    # the newest matching recipe; without either signal, stay unlinked.
    if version is not None:
        return max(candidates, key=lambda r: (r.created_at or utcnow(), r.id))
    return candidates[0] if len(candidates) == 1 else None


def training_record_for_checkpoint(dataset_id, family, checkpoint):
    record = _record_for_checkpoint(dataset_id, family, checkpoint)
    return record.id if record is not None else None


# En deçà de ce nombre de votes, un score est statistiquement fragile → drapeau
# « échantillon faible » dans l'UI (le tri reste Wilson, qui pénalise déjà les
# petits échantillons ; ce flag ne sert qu'à AVERTIR l'œil).
LOW_CONFIDENCE_MIN = 3

_GENERATION_CONFIG_FIELDS = (
    'checkpoint', 'strength', 'aspect', 'z_model', 'cfg', 'steps', 'steps2',
    'extra_loras', 'krea_rebalance', 'negative', 'sampler', 'scheduler',
    'weight_dtype', 'enhancer_strength', 'detail_amount', 'resolution_tier',
    'init_image', 'denoise',
)


def _normalized_extra_loras(value):
    try:
        parsed = json.loads(value or '[]')
    except (TypeError, json.JSONDecodeError):
        parsed = []
    return json.dumps(parsed, sort_keys=True, separators=(',', ':'))


def _generation_config(row) -> tuple:
    values = []
    for field in _GENERATION_CONFIG_FIELDS:
        value = getattr(row, field, None)
        values.append(_normalized_extra_loras(value) if field == 'extra_loras' else value)
    return tuple(values)


def _representative_image(dataset_id, config):
    target = tuple(config.get(field) for field in _GENERATION_CONFIG_FIELDS)
    target = tuple(_normalized_extra_loras(value) if field == 'extra_loras' else value
                   for field, value in zip(_GENERATION_CONFIG_FIELDS, target))
    rows = (LoraTestImage.query.filter_by(dataset_id=dataset_id, status='done')
            .order_by(LoraTestImage.id.desc()).all())
    return next((row for row in rows if _generation_config(row) == target), None)


def cell_scores(dataset_id, family=None, rows=None) -> list[dict]:
    """Score par CONFIG = (checkpoint, strength, format, modèle, cfg, steps),
    agrégé sur toutes les images de cette config (cross-runs). Le modèle fait
    partie de la clé : deux modèles sur la même case ne fusionnent plus.

    `family` (optionnel) restreint aux cellules de cette pipeline - déduite du
    dossier du checkpoint - pour que scores/best ne mélangent pas ZIT/SDXL/Krea d'un
    même dataset entraîné sous plusieurs familles. Un checkpoint sans préfixe de
    dossier (ancien nom) compte comme 'zimage'.

    `score` (👍−👎) reste exposé pour l'affichage, mais le TRI se fait sur `rank`
    = borne basse de Wilson sur le taux de 👍 (taux × confiance) - pas sur le
    compte brut, qui biaisait vers les configs simplement plus testées. Tri
    best-first : rank ↓, nb de votes ↓ (confiance), strength ↑ (anti-overfit)."""
    rows = (LoraTestImage.query.filter_by(dataset_id=dataset_id).all()
            if rows is None else list(rows))
    # Failed cells produced no image and can't be judged — exclude them so a broken
    # config doesn't inflate the 'images' denominator or otherwise pollute the
    # ranking / best-config pick (P0-b).
    rows = [r for r in rows if r.status == 'done']
    if family:
        fam = family.lower()
        rows = [r for r in rows if (family_of_lora(r.checkpoint) or 'zimage') == fam]
    agg = {}
    for r in rows:
        key = _generation_config(r)
        config = dict(zip(_GENERATION_CONFIG_FIELDS, key))
        e = agg.setdefault(key, {**config,
                                 'z_model_label': _model_label(r.z_model),
                                 'score': 0, 'likes': 0, 'dislikes': 0,
                                 'images': 0, 'voted': 0, 'rank': 0.0})
        e['images'] += 1
        if r.rating == 1:
            e['likes'] += 1
            e['voted'] += 1
        elif r.rating == -1:
            e['dislikes'] += 1
            e['voted'] += 1
    for e in agg.values():
        e['score'] = e['likes'] - e['dislikes']
        e['rank'] = round(_wilson_lower_bound(e['likes'], e['voted']), 4)
        # Taux d'approbation (likes/votés) - None si rien voté (pas de 0/0 trompeur).
        e['like_rate'] = round(e['likes'] / e['voted'], 4) if e['voted'] else None
        # Confiance : drapeau quand l'échantillon de votes est trop mince.
        e['low_confidence'] = e['voted'] < LOW_CONFIDENCE_MIN
    return sorted(agg.values(),
                  key=lambda e: (-e['rank'], -e['voted'], e['strength']))


def model_net_scores(dataset_id) -> dict:
    """Sentiment net par modèle (👍−👎 sur toutes ses images) - exposé pour
    l'affichage. Le gate de best_cell, lui, utilise le TAUX (voir _model_like_rates)."""
    rows = LoraTestImage.query.filter_by(dataset_id=dataset_id).all()
    net = {}
    for r in rows:
        if r.rating == 1:
            net[r.z_model] = net.get(r.z_model, 0) + 1
        elif r.rating == -1:
            net[r.z_model] = net.get(r.z_model, 0) - 1
    return net


def _model_like_rates(scores) -> dict:
    """Taux de 👍 par modèle (likes/voted) agrégé sur ses configs - sert à
    écarter un modèle globalement mal noté. {model: rate|None} (None = 0 vote)."""
    acc = {}
    for e in scores:
        likes, voted = acc.get(e['z_model'], (0, 0))
        acc[e['z_model']] = (likes + e['likes'], voted + e['voted'])
    return {m: (likes / voted if voted else None) for m, (likes, voted) in acc.items()}


def model_comparison(dataset_id, scores=None) -> list[dict]:
    """Agrégat de votes PAR modèle de base (z_model), pour comparer les bases
    ÉQUITABLEMENT. Classé par taux (Wilson lower bound), PAS par compte brut - qui
    favorise mécaniquement le modèle le plus testé (biais de volume). Chaque entrée
    porte images/voted pour rendre l'échantillon visible + low_confidence.

    `scores` partageable (cf. best_cell) pour éviter de re-scanner la table."""
    scores = cell_scores(dataset_id) if scores is None else scores
    acc = {}
    for e in scores:
        a = acc.setdefault(e['z_model'], {
            'z_model': e['z_model'], 'z_model_label': e['z_model_label'],
            'likes': 0, 'dislikes': 0, 'images': 0, 'voted': 0, 'checkpoints': set()})
        a['likes'] += e['likes']
        a['dislikes'] += e['dislikes']
        a['images'] += e['images']
        a['voted'] += e['voted']
        a['checkpoints'].add(e['checkpoint'])
    out = []
    for a in acc.values():
        out.append({
            'z_model': a['z_model'], 'z_model_label': a['z_model_label'],
            'likes': a['likes'], 'dislikes': a['dislikes'],
            'net': a['likes'] - a['dislikes'],
            'images': a['images'], 'voted': a['voted'],
            'like_rate': round(a['likes'] / a['voted'], 4) if a['voted'] else None,
            'wilson': round(_wilson_lower_bound(a['likes'], a['voted']), 4),
            'low_confidence': a['voted'] < LOW_CONFIDENCE_MIN,
            'n_checkpoints': len(a['checkpoints']),
        })
    out.sort(key=lambda m: (-m['wilson'], -m['voted']))
    return out


def checkpoint_model_breakdown(dataset_id, scores=None) -> list[dict]:
    """Par (checkpoint, z_model) : nb d'images générées / votées + taux de 👍.
    C'est le « nombre de générées par modèle, par LoRA » - le dénominateur qui
    montre où l'échantillon est mince (ex. Lola testé 12× sur bigLove vs 3× sur
    l'officiel). Trié par label de checkpoint puis taux décroissant.

    `scores` partageable (cf. best_cell)."""
    scores = cell_scores(dataset_id) if scores is None else scores
    acc = {}
    for e in scores:
        key = (e['checkpoint'], e['z_model'])
        a = acc.setdefault(key, {
            'checkpoint': e['checkpoint'],
            'label': format_trained_lora_label(e['checkpoint']) or _basename(e['checkpoint']).rsplit('.', 1)[0],
            'z_model': e['z_model'], 'z_model_label': e['z_model_label'],
            'likes': 0, 'dislikes': 0, 'images': 0, 'voted': 0})
        a['likes'] += e['likes']
        a['dislikes'] += e['dislikes']
        a['images'] += e['images']
        a['voted'] += e['voted']
    out = []
    for a in acc.values():
        a['net'] = a['likes'] - a['dislikes']
        a['like_rate'] = round(a['likes'] / a['voted'], 4) if a['voted'] else None
        a['low_confidence'] = a['voted'] < LOW_CONFIDENCE_MIN
        out.append(a)
    out.sort(key=lambda a: (a['label'], -(a['like_rate'] or 0), -a['voted']))
    return out


def _feedback_for_records(records):
    """Aggregate Studio evidence by immutable training launch.

    Returns ``(record_id -> metrics, unlinked summary)``.  Failed/pending cells
    are not evidence; completed but unvoted cells still count as test coverage.
    """
    records = list(records or [])
    records_by_id = {record.id: record for record in records}
    by_scope = {}
    for record in records:
        by_scope.setdefault((record.dataset_id, record.family), []).append(record)
    out = {}
    cell_agg = {}
    for record in records:
        settings = _json_object(record.settings)
        overrides = _json_object(record.overrides)
        out[record.id] = {
            'record_id': record.id, 'dataset_id': record.dataset_id,
            'family': record.family, 'version': record.version,
            'source': record.source, 'steps': record.steps,
            'created_at': record.created_at.isoformat() if record.created_at else None,
            'images': 0, 'voted': 0, 'likes': 0, 'dislikes': 0,
            'like_rate': None, 'wilson': 0.0, 'confidence': 'none',
            'face_scored': 0, 'mean_face_score': None,
            'best_checkpoint': None, 'best_strength': None, 'best_step': None,
            'checkpoints': [], 'recipe': settings,
            'admission_override_count': sum(1 for value in overrides.values() if value),
        }
    unlinked = {'images': 0, 'voted': 0, 'likes': 0, 'dislikes': 0}
    if not by_scope:
        return out, unlinked
    dataset_ids = sorted({key[0] for key in by_scope})
    rows = (LoraTestImage.query
            .filter(LoraTestImage.dataset_id.in_(dataset_ids),
                    LoraTestImage.status == 'done',
                    LoraTestImage.filename.isnot(None)).all())
    face_sums = {}
    checkpoints = {}
    for row in rows:
        # New rows carry exact immutable provenance.  Trust that link before
        # filename/folder inference, but only when it belongs to this dataset;
        # a stale/corrupt cross-dataset id must never reattribute evidence.
        record = records_by_id.get(row.training_run_record_id)
        if record is not None and record.dataset_id != row.dataset_id:
            record = None
        if record is None:
            family = (family_of_lora(row.checkpoint) or 'zimage').lower()
            scoped = by_scope.get((row.dataset_id, family), [])
            record = _record_for_checkpoint(
                row.dataset_id, family, row.checkpoint, records=scoped)
        if record is None:
            unlinked['images'] += 1
            if row.rating == 1:
                unlinked['likes'] += 1
                unlinked['voted'] += 1
            elif row.rating == -1:
                unlinked['dislikes'] += 1
                unlinked['voted'] += 1
            continue
        stats = out[record.id]
        stats['images'] += 1
        checkpoints.setdefault(record.id, set()).add(row.checkpoint)
        if row.rating == 1:
            stats['likes'] += 1
            stats['voted'] += 1
        elif row.rating == -1:
            stats['dislikes'] += 1
            stats['voted'] += 1
        if row.face_score is not None:
            face_sums[record.id] = face_sums.get(record.id, 0.0) + float(row.face_score)
            stats['face_scored'] += 1
        key = (record.id, row.checkpoint, row.strength)
        cell = cell_agg.setdefault(key, {
            'record_id': record.id, 'checkpoint': row.checkpoint,
            'strength': row.strength, 'likes': 0, 'dislikes': 0, 'voted': 0,
        })
        if row.rating == 1:
            cell['likes'] += 1
            cell['voted'] += 1
        elif row.rating == -1:
            cell['dislikes'] += 1
            cell['voted'] += 1

    for record_id, stats in out.items():
        if stats['voted']:
            stats['like_rate'] = round(stats['likes'] / stats['voted'], 4)
            stats['wilson'] = round(
                _wilson_lower_bound(stats['likes'], stats['voted']), 4)
            stats['confidence'] = ('low' if stats['voted'] < LOW_CONFIDENCE_MIN
                                   else 'moderate' if stats['voted'] < 8
                                   else 'higher')
        elif stats['images']:
            stats['confidence'] = 'unvoted'
        if stats['face_scored']:
            stats['mean_face_score'] = round(
                face_sums[record_id] / stats['face_scored'], 4)
        stats['checkpoints'] = sorted(checkpoints.get(record_id, set()))
        candidates = [cell for key, cell in cell_agg.items()
                      if key[0] == record_id and cell['voted']]
        if candidates:
            candidates.sort(key=lambda cell: (
                -_wilson_lower_bound(cell['likes'], cell['voted']),
                -cell['voted'], -(cell['likes'] - cell['dislikes']),
                cell['strength']))
            best = candidates[0]
            stats['best_checkpoint'] = best['checkpoint']
            stats['best_strength'] = best['strength']
            stats['best_step'] = _checkpoint_step(best['checkpoint'])
    return out, unlinked


def feedback_for_records(records):
    """Public batch helper used by the unified Runs hub."""
    return _feedback_for_records(records)[0]


def training_feedback(user_id, dataset_id, family=None) -> dict | None:
    """Close Studio ratings back into the next training decision.

    Recommendations are deliberately evidence-gated: fewer than three votes
    never produces a quality verdict, and unlinked historical cells are called
    out instead of silently assigned to the latest run.
    """
    ds = fds.get_dataset(user_id, dataset_id)
    if ds is None:
        return None
    eff = (family or getattr(ds, 'train_type', None) or 'zimage').lower()
    records = (TrainingRunRecord.query
               .filter_by(dataset_id=dataset_id, family=eff)
               .order_by(TrainingRunRecord.created_at.desc(),
                         TrainingRunRecord.id.desc()).limit(100).all())
    mapped, unlinked = _feedback_for_records(records)
    runs = [mapped[record.id] for record in records]
    recommendations = []

    def recommend(kind, title, detail):
        recommendations.append({'kind': kind, 'title': title, 'detail': detail})

    if not records:
        summary = 'No training launch is registered for this family yet.'
        recommend('train', 'Create a provenance-backed run',
                  'Train once, import a checkpoint, then validate it in Studio.')
    else:
        latest = runs[0]
        evaluated = [run for run in runs if run['voted']]
        if not evaluated:
            summary = f"Dataset v{latest['version']} has no rated Studio evidence yet."
            recommend('validate', 'Test the latest run before changing the recipe',
                      'Generate a fixed-seed Studio sweep and rate at least three outputs.')
        else:
            best = max(evaluated, key=lambda run: (run['wilson'], run['voted']))
            summary = (f"Best measured run is v{best['version']}: "
                       f"{best['likes']}/{best['voted']} liked "
                       f"({round((best['like_rate'] or 0) * 100)}%).")
            if latest['voted'] < LOW_CONFIDENCE_MIN:
                recommend('validate', f"Collect more evidence for v{latest['version']}",
                          f"Only {latest['voted']} rated output(s) are linked to the latest run; "
                          f"{LOW_CONFIDENCE_MIN} is the minimum before drawing a direction.")
            elif (latest['like_rate'] or 0) >= 0.7:
                recommend('preserve', 'Keep the latest training recipe as the baseline',
                          'Its measured approval is positive; change one variable at a time in the next run.')
            elif (latest['like_rate'] or 0) <= 0.4:
                recommend('dataset', 'Review data and captions before adding training steps',
                          'Dislikes dominate the latest run; more steps can reinforce the same dataset problems.')
            else:
                recommend('iterate', 'Run a controlled single-variable iteration',
                          'The latest result is mixed; preserve the dataset version and change one recipe setting.')
            if best['record_id'] != latest['record_id'] and best['voted'] >= LOW_CONFIDENCE_MIN:
                recommend('compare', f"Compare against v{best['version']} before proceeding",
                          'An older run currently has stronger vote evidence than the latest launch.')
            if (best['best_step'] and best['steps']
                    and best['best_step'] < int(best['steps'] * 0.8)):
                recommend('early_stop', f"Validate around step {best['best_step']}",
                          f"The best-rated checkpoint arrived well before the {best['steps']}-step target; "
                          'an earlier stop may avoid over-training and reduce compute.')
            if best['best_strength'] is not None:
                recommend('inference', f"Start validation near strength {best['best_strength']:g}",
                          'This is the best-rated Studio strength for the strongest measured run.')
    if unlinked['images']:
        recommend('provenance', 'Retest historical unlinked checkpoints',
                  f"{unlinked['images']} completed Studio image(s) predate an exact launch link and are excluded from run comparison.")
    return {
        'family': eff, 'summary': summary, 'runs': runs,
        'recommendations': recommendations, 'unlinked': unlinked,
        'minimum_votes': LOW_CONFIDENCE_MIN,
    }


def best_cell(dataset_id, scores=None) -> dict | None:
    """Config recommandée d'après les votes :
      1. candidats = configs nettes positives (👍 > 👎) ;
      2. tri par `rank` Wilson ↓ (taux × confiance) - le MÉRITE de la config prime ;
      3. départages : nb de votes ↓ (confiance), puis taux de 👍 GLOBAL du modèle ↓
         (à config équivalente, on préfère le modèle mieux noté), puis strength ↑.
    Le sentiment du modèle est un DÉPARTAGE, pas un filtre : une config nettement
    mieux notée n'est jamais écartée parce que son modèle est moyen ailleurs (sinon
    le sweep par-case n'aurait aucun sens). Retourne None tant que rien n'est aimé.

    `scores` peut être passé (déjà calculé) pour éviter de re-scanner la table -
    studio_payload partage un seul cell_scores entre best_cell/best_preset/best_per_checkpoint."""
    scores = cell_scores(dataset_id) if scores is None else scores
    candidates = [e for e in scores if e['likes'] > e['dislikes']]
    if not candidates:
        return None
    rates = _model_like_rates(scores)

    def model_pref(m):
        r = rates.get(m)
        return r if r is not None else 0.5  # modèle sans vote = neutre
    candidates.sort(key=lambda e: (-e['rank'], -e['voted'],
                                   -model_pref(e['z_model']), e['strength']))
    return candidates[0]


def best_preset(dataset_id, scores=None) -> dict | None:
    """La config recommandée (best_cell, modèle inclus) enrichie d'une image
    représentative (prompt/seed/filename) de CETTE config exacte."""
    bc = best_cell(dataset_id, scores=scores)
    if not bc:
        return None
    img = _representative_image(dataset_id, bc)
    return {
        **bc,
        'label': format_trained_lora_label(bc['checkpoint']) or _basename(bc['checkpoint']).rsplit('.', 1)[0],
        'prompt': getattr(img, 'prompt', None) if img else None,
        'seed': img.seed if img else None,
        'filename': img.filename if img else None,
    }


def best_per_checkpoint(dataset_id, scores=None) -> list[dict]:
    """Meilleur réglage PAR checkpoint (les votes varient beaucoup d'un modèle à
    l'autre - un best global ne suffit pas). Pour chaque checkpoint ayant ≥1 config
    nette positive (👍>👎), retourne sa config la mieux notée (MÊME tri Wilson que
    best_cell), enrichie d'une image représentative. Trié par rank décroissant.

    `scores` partageable (cf. best_cell) pour éviter de re-scanner la table."""
    scores = cell_scores(dataset_id) if scores is None else scores
    candidates = [e for e in scores if e['likes'] > e['dislikes']]
    if not candidates:
        return []
    rates = _model_like_rates(scores)

    def model_pref(m):
        r = rates.get(m)
        return r if r is not None else 0.5
    candidates.sort(key=lambda e: (-e['rank'], -e['voted'],
                                   -model_pref(e['z_model']), e['strength']))
    best_by_cp = {}
    for e in candidates:  # déjà triés → le 1er vu par checkpoint = le meilleur
        best_by_cp.setdefault(e['checkpoint'], e)
    out = []
    for bc in best_by_cp.values():
        img = _representative_image(dataset_id, bc)
        out.append({**bc,
                    'label': format_trained_lora_label(bc['checkpoint']) or _basename(bc['checkpoint']).rsplit('.', 1)[0],
                    'prompt': getattr(img, 'prompt', None) if img else None,
                    'seed': img.seed if img else None,
                    'filename': img.filename if img else None})
    out.sort(key=lambda e: -e['rank'])
    return out


def _best_map(ds) -> dict:
    """best_settings persistés en map {famille: réglage}. RÉTRO-COMPAT : un ancien
    format PLAT (un seul réglage, repérable à sa clé top-level `lora_filename`) est
    rattaché au train_type du dataset. Retourne {} si vide/illisible."""
    if not ds.best_settings:
        return {}
    try:
        data = json.loads(ds.best_settings)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    if 'lora_filename' in data:  # ancien format plat (mono-famille)
        return {(getattr(ds, 'train_type', None) or 'zimage').lower(): data}
    return data


def _best_for_family(ds, family) -> dict | None:
    """Réglage mémorisé pour CETTE famille (None si aucun)."""
    return _best_map(ds).get((family or 'zimage').lower())


def set_best_settings(user_id, dataset_id, checkpoint, strength,
                      z_model=None, cfg=None, steps=None, steps2=None, aspect=None,
                      generation_config=None) -> dict:
    """Persiste la config gagnante COMPLÈTE - checkpoint, strength, modèle/cfg/steps(1+2)/
    format. Mémorisé PAR FAMILLE (un même dataset a un meilleur réglage distinct en ZIT,
    SDXL, Krea) : la famille est déduite du dossier du checkpoint. Le checkpoint doit
    appartenir à la whitelist de SA famille ; le modèle, s'il est fourni, est validé
    contre les bases du bon type (Krea = base fixe → modèle ignoré). Retourne le réglage."""
    ds = fds.get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    family = (family_of_lora(checkpoint) or getattr(ds, 'train_type', None) or 'zimage').lower()
    allowed = {c['filename'] for c in list_test_checkpoints(ds, family)}
    if checkpoint not in allowed:
        raise ValueError('unknown checkpoint for this dataset')
    try:
        strength = round(float(strength), 2)
    except (TypeError, ValueError):
        raise ValueError(f'invalid strength: {strength!r}')
    if not 0.0 <= strength <= 2.0:
        raise ValueError(f'strength out of range: {strength}')
    # Whitelist de bases selon la FAMILLE (SDXL → bases SDXL ; Krea → UNET locaux
    # scannés ; sinon Z-Image), sinon une base d'une autre famille était jetée.
    if family == 'sdxl':
        allowed_bases = {m['filename'] for m in list_sdxl_base_models()}
    elif family == 'krea':
        allowed_bases = set(get_krea_models())
    else:
        allowed_bases = set(get_zimage_models())
    z_model = z_model or None  # '' (entrée « Official » Krea) ≡ défaut → NULL
    if z_model and z_model not in allowed_bases:
        z_model = None  # modèle inconnu → on ne l'enregistre pas (au lieu de mentir)
    try:
        cfg = round(float(cfg), 2) if cfg is not None else None
    except (TypeError, ValueError):
        cfg = None
    try:
        steps = int(steps) if steps is not None else None
    except (TypeError, ValueError):
        steps = None
    try:
        steps2 = int(steps2) if steps2 is not None else None
    except (TypeError, ValueError):
        steps2 = None
    aspect = aspect if aspect in TEST_ASPECTS else None
    best = {
        'lora_filename': checkpoint,
        'strength': strength,
        'z_model': z_model,
        'cfg': cfg,
        'steps': steps,
        'steps2': steps2,
        'aspect': aspect,
        'family': family,
        'decided_at': utcnow().isoformat(),
    }
    # Preserve the exact tested winner, including batch and workflow controls.
    # The individually validated fields above remain authoritative for legacy
    # callers; optional fields are copied only from the canonical config schema.
    supplied = generation_config if isinstance(generation_config, dict) else {}
    for field in _GENERATION_CONFIG_FIELDS:
        if field in best or field not in supplied:
            continue
        value = supplied[field]
        if field == 'extra_loras':
            try:
                value = json.loads(_normalized_extra_loras(value))
            except (TypeError, json.JSONDecodeError):
                value = []
        best[field] = value
    best_map = _best_map(ds)
    best_map[family] = best
    ds.best_settings = json.dumps(best_map)
    db.session.commit()
    return best


def clear_best_settings(user_id, dataset_id, family=None) -> bool:
    """Efface le réglage mémorisé. `family` → n'efface que cette famille (les autres
    survivent) ; absent → efface tout. Idempotent (pas d'erreur s'il n'y a rien)."""
    ds = fds.get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    if family:
        m = _best_map(ds)
        m.pop((family or '').lower(), None)
        ds.best_settings = json.dumps(m) if m else None
    else:
        ds.best_settings = None
    db.session.commit()
    return True


# --- Scoring facial objectif (« best epoch » auto - méthode jandordoe) --------
def _matched_face_cohort(dataset_id, family):
    """Return the newest launch's rows that have like-for-like checkpoint samples."""
    rows = (LoraTestImage.query.filter_by(dataset_id=dataset_id, status='done')
            .filter(LoraTestImage.filename.isnot(None)).order_by(LoraTestImage.id.desc()).all())
    rows = [row for row in rows if (family_of_lora(row.checkpoint) or 'zimage') == family]
    launches = {}
    for row in rows:
        launch = row.run_id or f'legacy:{row.run_seed}:{row.prompt or ""}'
        launches.setdefault(launch, []).append(row)
    for launch_rows in launches.values():
        checkpoints = {row.checkpoint for row in launch_rows}
        if len(checkpoints) < 2:
            continue
        signatures = {}
        for row in launch_rows:
            signature = (row.strength, row.seed, row.prompt, row.z_model, row.aspect,
                         row.cfg, row.steps, row.steps2)
            signatures.setdefault(signature, set()).add(row.checkpoint)
        matched = {signature for signature, present in signatures.items()
                   if present == checkpoints}
        cohort = [row for row in launch_rows if (
            row.strength, row.seed, row.prompt, row.z_model, row.aspect,
            row.cfg, row.steps, row.steps2) in matched]
        if cohort:
            return cohort
    return []


def score_faces(user_id, dataset_id, family=None) -> dict:
    """Score InsightFace (antelopev2, subprocess CPU - ne touche PAS le GPU) de
    chaque cellule TERMINÉE de la famille vs la RÉFÉRENCE du dataset. Persiste
    face_score/face_state par cellule, puis renvoie le classement par checkpoint.

    C'est l'automatisation de la méthode jandordoe : générer les checkpoints à
    seed fixe (le Studio le fait déjà), puis choisir l'epoch au MEILLEUR score
    facial mesuré au lieu du dernier. Idempotent : rescorer écrase les scores."""
    ds = fds.get_dataset(user_id, dataset_id)
    if not ds:
        raise ValueError('dataset not found')
    if not ds.ref_filename:
        raise ValueError('reference photo missing')
    ref_path = fds._ref_path(ds)
    if not os.path.exists(ref_path):
        raise ValueError('reference photo missing')
    eff = _resolve_family(ds, family, available_families(ds))
    rows = _matched_face_cohort(dataset_id, eff)
    ds_dir = fds._dataset_dir(dataset_id)
    by_path = {}
    for r in rows:
        p = os.path.join(ds_dir, r.filename)
        if os.path.exists(p):
            by_path[p] = r
    if not by_path:
        return {'scored': 0, 'total': 0, 'scoring_error': None, 'ranking': []}
    from .face_similarity import score_dataset_faces
    # scoring_error ({kind, detail} | None) remonte jusqu'au toast : un scorer
    # cassé doit dire POURQUOI, pas « done — 0/14 » en vert (user-reported).
    results, scoring_error = score_dataset_faces(ref_path, list(by_path.keys()))
    scored = 0
    for p, r in by_path.items():
        res = results.get(p)
        if not res:
            continue
        r.face_state = res.get('state')
        r.face_score = res.get('sim')
        scored += 1
    db.session.commit()
    logger.info(f"lora-test: score-faces dataset {dataset_id} ({eff}) -> "
                f"{scored}/{len(by_path)} cellule(s) scorée(s)")
    return {'scored': scored, 'total': len(by_path), 'scoring_error': scoring_error,
            'ranking': face_ranking(dataset_id, eff)}


def face_ranking(dataset_id, family, rows=None) -> list:
    """Classement des checkpoints par similarité faciale MOYENNE (cellules déjà
    scorées, famille donnée). [{checkpoint, label, avg, n}] trié meilleur d'abord -
    le front marque le 1er comme « 🏆 best epoch »."""
    source = rows if rows is not None else _matched_face_cohort(dataset_id, family)
    rows = [row for row in source if row.face_score is not None]
    agg = {}
    for r in rows:
        a = agg.setdefault(r.checkpoint, [0.0, 0])
        a[0] += float(r.face_score)
        a[1] += 1
    out = [{'checkpoint': cp,
            'label': format_trained_lora_label(cp) or _basename(cp).rsplit('.', 1)[0],
            'avg': round(s / n, 4), 'n': n}
           for cp, (s, n) in agg.items()]
    out.sort(key=lambda e: (-e['avg'], -e['n']))
    return out
