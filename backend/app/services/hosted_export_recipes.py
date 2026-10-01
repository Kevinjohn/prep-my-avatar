"""Versioned offline target definitions and bounded archive formatters.

Adding a recipe requires a maintained definition and, when necessary, a formatter
here. Corpus admission and selection do not depend on a service implementation.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

_DEFINITION_PATH = Path(__file__).with_name('export_recipes') / 'fal-krea-reviewed-v1.json'
DEFINITIONS = {}
if _DEFINITION_PATH.is_file():
    _initial = json.loads(_DEFINITION_PATH.read_text(encoding='utf-8'))
    DEFINITIONS[(_initial['id'], _initial['version'])] = _initial


def get_recipe(recipe_id, version):
    if not isinstance(recipe_id, str) or type(version) is not int:
        raise ValueError('recipe id and integer version are required')
    definition = DEFINITIONS.get((recipe_id, version))
    if definition is None:
        raise ValueError('unsupported export recipe revision')
    definition = copy.deepcopy(definition)
    if (definition.get('format') != 'person-export-recipe'
            or definition.get('schema_version') != 1
            or definition.get('id') != recipe_id or definition.get('version') != version
            or not isinstance(definition.get('model_id'), str)
            or not definition['model_id'].strip()):
        raise ValueError('invalid versioned export recipe definition')
    if (definition.get('crop_rule') not in ('square', 'preserve')
            or definition.get('formatter') not in FORMATTERS
            or Path(definition.get('archive_name', '')).name != definition.get('archive_name')
            or not definition.get('archive_name', '').endswith('.zip')):
        raise ValueError('invalid export recipe definition')
    supported_tasks = definition.get('supported_tasks')
    if (not isinstance(supported_tasks, list) or not supported_tasks
            or any(not isinstance(task, str) or not task.strip() for task in supported_tasks)
            or definition.get('purpose') not in supported_tasks):
        raise ValueError('recipe purpose is incompatible with supported task capabilities')
    service = definition.get('service', {})
    if (service.get('protocol') != 'manual-offline'
            or definition.get('base_family') not in service.get('supported_base_families', [])
            or definition.get('asset_kind') not in service.get('supported_asset_kinds', [])):
        raise ValueError('recipe has incompatible service/base family')
    requirements = definition.get('input_requirements', {})
    minimum = requirements.get('minimum_training_images')
    if (type(minimum) is not int or minimum < 1 or minimum > 10000
            or requirements.get('subject_kind') != 'character'
            or requirements.get('reviewed_caption_pairs') is not True):
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
