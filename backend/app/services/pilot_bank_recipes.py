"""Maintained manual candidate recipes, separate from training-export recipes.

These settings never execute a provider request or establish compatibility.
"""
import hashlib
import json
from pathlib import Path


def list_recipes():
    result = []
    for path in sorted((Path(__file__).parent / 'pilot_recipes').glob('*.json')):
        raw = path.read_bytes()
        definition = json.loads(raw)
        definition['definition_sha256'] = hashlib.sha256(raw).hexdigest()
        result.append(definition)
    return result
