"""Versioned offline target definitions and bounded archive formatters.

Adding a recipe requires a maintained definition and, when necessary, a formatter
here. Corpus admission and selection do not depend on a service implementation.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

DEFINITIONS = {}
for _path in sorted(Path(__file__).with_name('export_recipes').glob('*.json')):
    _initial = json.loads(_path.read_text(encoding='utf-8'))
    _key = (_initial['id'], _initial['version'])
    if _key in DEFINITIONS:
        raise ValueError('duplicate maintained export recipe revision')
    DEFINITIONS[_key] = _initial


def role_minima(definition):
    requirements = definition['input_requirements']
    minima = dict(requirements.get('minimum_images_by_role', {}))
    if 'minimum_training_images' in requirements:
        minima['training'] = requirements['minimum_training_images']
    return minima


def get_recipe(recipe_id, version):
    if not isinstance(recipe_id, str) or type(version) is not int:
        raise ValueError('recipe id and integer version are required')
    definition = DEFINITIONS.get((recipe_id, version))
    if definition is None:
        raise ValueError('unsupported export recipe revision')
    definition = copy.deepcopy(definition)
    reference_pack = definition.get('purpose') == 'reference-preparation'
    if (definition.get('format') != 'person-export-recipe'
            or definition.get('schema_version') != 1
            or definition.get('id') != recipe_id or definition.get('version') != version
            or (not reference_pack and (not isinstance(definition.get('model_id'), str)
                                       or not definition['model_id'].strip()))):
        raise ValueError('invalid versioned export recipe definition')
    definition.setdefault('supported_roles', ['training', 'reference', 'evaluation'])
    roles = definition['supported_roles']
    if (not isinstance(roles, list) or not roles
            or any(role not in ('training', 'reference', 'evaluation') for role in roles)
            or len(set(roles)) != len(roles)):
        raise ValueError('invalid supported export roles')
    if reference_pack:
        if (roles != ['reference', 'evaluation'] or definition.get('crop_rule') != 'preserve'
                or definition.get('formatter') is not None or definition.get('archive_name') is not None
                or any(definition.get(key) is not None for key in
                       ('model_id', 'base_family', 'asset_kind', 'endpoint'))):
            raise ValueError('invalid reference preparation definition')
    elif (definition.get('crop_rule') not in ('square', 'preserve')
            or definition.get('formatter') not in FORMATTERS
            or not isinstance(definition.get('archive_name'), str)
            or Path(definition['archive_name']).name != definition['archive_name']
            or not definition['archive_name'].endswith('.zip')):
        raise ValueError('invalid export recipe definition')
    supported_tasks = definition.get('supported_tasks')
    if (not isinstance(supported_tasks, list) or not supported_tasks
            or any(not isinstance(task, str) or not task.strip() for task in supported_tasks)
            or definition.get('purpose') not in supported_tasks):
        raise ValueError('recipe purpose is incompatible with supported task capabilities')
    service = definition.get('service', {})
    if (service.get('protocol') != 'manual-offline'
            or (not reference_pack and (
                definition.get('base_family') not in service.get('supported_base_families', [])
                or definition.get('asset_kind') not in service.get('supported_asset_kinds', [])))):
        raise ValueError('recipe has incompatible service/base family')
    requirements = definition.get('input_requirements', {})
    supplied_minima = requirements.get('minimum_images_by_role', {})
    if not isinstance(supplied_minima, dict):
        raise ValueError('invalid role minima')
    minima = role_minima(definition)
    if (not minima or set(minima) - set(roles)
            or any(type(value) is not int or value < 0 or value > 10000 for value in minima.values())
            or requirements.get('subject_kind') != 'character'
            or requirements.get('reviewed_caption_pairs') is not True
            or (reference_pack and minima.get('reference', 0) < 1)
            or (not reference_pack and minima.get('training', 0) < 1)):
        raise ValueError('unsupported recipe input requirements')
    parameters(definition, {})
    return definition


def parameters(definition, supplied):
    if not isinstance(supplied, dict):
        raise ValueError('parameters must be an object')
    specs = definition['parameters']
    if set(supplied) - set(specs):
        raise ValueError('unsupported recipe parameter')
    result = {**definition['defaults'], **supplied}
    if set(result) != set(specs):
        raise ValueError('recipe defaults must specify every supported parameter')
    for name, value in result.items():
        spec = specs[name]
        kind = spec['type']
        valid = ((kind == 'integer' and type(value) is int)
                 or (kind == 'number' and type(value) in (float, int) and math.isfinite(value))
                 or (kind == 'boolean' and type(value) is bool)
                 or (kind == 'string' and isinstance(value, str)))
        if (not valid or ('enum' in spec and value not in spec['enum'])
                or ('minimum' in spec and value < spec['minimum'])
                or ('maximum' in spec and value > spec['maximum'])):
            raise ValueError(f'invalid recipe parameter: {name}')
    return result


def _paired_root(stem):
    return f'{stem}.png', f'{stem}.txt'


def _paired_folder(stem):
    return f'images/{stem}.png', f'images/{stem}.txt'


FORMATTERS = {'paired-root': _paired_root, 'paired-folder': _paired_folder}


def pair_names(definition, stem):
    return FORMATTERS[definition['formatter']](stem)
