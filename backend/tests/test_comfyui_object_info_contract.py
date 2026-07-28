import json
from pathlib import Path

import pytest


BACKEND = Path(__file__).parents[1]
FIXTURES = Path(__file__).parent / 'fixtures' / 'comfyui'
ACTIVE_WORKFLOWS = sorted(
    path for path in (BACKEND / 'workflows').glob('*.json')
    if path.name != 'sampler_params.json'
)


def _object_info():
    merged = {}
    for name in ('object_info-core-v1.json', 'object_info-custom-fake-v1.json'):
        payload = json.loads((FIXTURES / name).read_text())
        assert not set(merged) & set(payload), f'duplicate object_info class in {name}'
        merged.update(payload)
    return merged


@pytest.mark.parametrize('workflow_path', ACTIVE_WORKFLOWS, ids=lambda path: path.name)
def test_active_workflow_matches_versioned_object_info_input_schema(workflow_path):
    object_info = _object_info()
    workflow = json.loads(workflow_path.read_text())
    assert isinstance(workflow, dict) and workflow
    for node_id, node in workflow.items():
        assert isinstance(node, dict), f'{workflow_path.name}:{node_id} is not an object'
        class_type = node.get('class_type')
        assert class_type in object_info, (
            f'{workflow_path.name}:{node_id} uses unknown node {class_type!r}')
        schema = object_info[class_type].get('input', {})
        accepted = set(schema.get('required', {})) | set(schema.get('optional', {}))
        unexpected = set(node.get('inputs', {})) - accepted
        assert not unexpected, (
            f'{workflow_path.name}:{node_id} {class_type} has unsupported inputs '
            f'{sorted(unexpected)}')


def test_object_info_fixture_set_has_no_unused_node_schema():
    used = set()
    for path in ACTIVE_WORKFLOWS:
        used.update(node['class_type'] for node in json.loads(path.read_text()).values())
    assert set(_object_info()) == used
