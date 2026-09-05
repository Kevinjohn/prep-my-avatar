"""RunPod REST pods and GraphQL GPU catalogue, using fresh credentials per call."""

import logging

import requests

from .. import config as cfg
from .cloud_provider import ProviderError

logger = logging.getLogger(__name__)
API_BASE = 'https://rest.runpod.io/v1'
GRAPHQL_URL = 'https://api.runpod.io/graphql'


class RunpodError(ProviderError):
    pass


def _request(method, path='', *, graphql=False, **kwargs):
    key = cfg.secret('RUNPOD_API_KEY')
    if not key:
        raise RunpodError('RUNPOD_API_KEY is not configured')
    if graphql:
        kwargs['params'] = {'api_key': key}
    try:
        return requests.request(
            method,
            GRAPHQL_URL if graphql else API_BASE + path,
            headers={'Authorization': f'Bearer {key}', 'Accept': 'application/json'},
            timeout=30,
            **kwargs,
        )
    except requests.RequestException as exc:
        # Request exceptions can contain the GraphQL URL, including its key.
        raise RunpodError('RunPod request failed') from exc


def _json(response):
    if not 200 <= response.status_code < 300:
        raise RunpodError(
            f'RunPod returned HTTP {response.status_code}: {response.text}'
        )
    try:
        return response.json()
    except (TypeError, ValueError) as exc:
        raise RunpodError('RunPod returned malformed JSON') from exc


def graphql(query):
    data = _json(_request('POST', graphql=True, json={'query': query}))
    if (
        not isinstance(data, dict)
        or data.get('errors')
        or not isinstance(data.get('data'), dict)
    ):
        raise RunpodError('RunPod GraphQL returned an invalid response or errors')
    return data['data']


def search_offers(
    min_vram_gb: int,
    max_dph: float,
    limit: int = 20,
    min_inet_down_mbps: int = 0,
    min_reliability: float = 0.95,
    min_disk_bw_mbps: int = 0,
) -> list:
    secure = cfg.get('cloud.runpod.cloud_type') != 'COMMUNITY'
    query = (
        '{ gpuTypes { id displayName memoryInGb secureCloud communityCloud '
        'lowestPrice(input: {gpuCount: 1, secureCloud: '
        + str(secure).lower()
        + '}) { uninterruptablePrice stockStatus } } }'
    )
    offers = []
    for gpu in graphql(query).get('gpuTypes') or []:
        price = gpu.get('lowestPrice') or {}
        dph = price.get('uninterruptablePrice')
        stock = price.get('stockStatus')
        memory = gpu.get('memoryInGb') or 0
        if (
            not gpu.get('id')
            or memory < min_vram_gb
            or dph is None
            or dph > max_dph
            or stock in (None, 'None')
        ):
            continue
        offers.append(
            {
                'offer_id': gpu['id'],
                'gpu_name': gpu.get('displayName'),
                'dph_total': dph,
                'gpu_ram_gb': memory,
                'machine_id': None,
                'reliability': None,
                'stock_status': stock,
            }
        )
    return sorted(offers, key=lambda offer: offer['dph_total'])[:limit]


def create_instance(
    offer_id,
    disk_gb: int,
    label: str,
    template_hash: str | None = None,
    image: str | None = None,
    env: dict | None = None,
    onstart: str | None = None,
) -> str:
    port = int(cfg.get('cloud.runpod.ui_port') or 8675)
    body = {
        'name': label,
        'imageName': image or cfg.get('cloud.runpod.image'),
        'gpuTypeIds': [offer_id],
        'gpuCount': 1,
        'cloudType': cfg.get('cloud.runpod.cloud_type') or 'SECURE',
        'containerDiskInGb': int(disk_gb),
        'volumeInGb': 0,
        'ports': [f'{port}/http'],
        'env': {k: v for k, v in (env or {}).items() if not k.startswith('-')},
    }
    if template_hash:
        body['templateId'] = template_hash
    response = _request('POST', '/pods', json=body)
    if 400 <= response.status_code < 500 and any(
        word in response.text.lower()
        for word in ('stock', 'capacity', 'available', 'availability')
    ):
        raise RunpodError(
            f'no RunPod capacity for {offer_id} right now — open the '
            'GPU picker and choose another tier'
        )
    data = _json(response)
    if (
        not isinstance(data, dict)
        or not isinstance(data.get('id'), str)
        or not data['id'].strip()
    ):
        raise RunpodError('RunPod create succeeded without a valid pod id')
    return data['id']


def _normalize(pod):
    status = (pod.get('desiredStatus') or '').lower()
    iid = str(pod.get('id'))
    ports = {}
    if status == 'running':
        for declared in pod.get('ports') or []:
            port, _, protocol = declared.partition('/')
            if protocol == 'http':
                ports[f'{port}/tcp'] = [
                    {'HostIp': f'{iid}-{port}.proxy.runpod.net', 'HostPort': 443}
                ]
    return {
        'instance_id': iid,
        'actual_status': status,
        'public_ipaddr': pod.get('publicIp'),
        'ports': ports,
        'label': pod.get('name'),
        'dph_total': pod.get('costPerHr'),
        'jupyter_token': None,
    }


def list_instances() -> list:
    data = _json(_request('GET', '/pods'))
    if not isinstance(data, list):
        raise RunpodError('RunPod returned an invalid pod list')
    return [_normalize(pod) for pod in data]


def get_instance(instance_id):
    response = _request('GET', f'/pods/{instance_id}')
    if response.status_code == 404:
        return None
    data = _json(response)
    if not isinstance(data, dict):
        raise RunpodError('RunPod returned an invalid pod')
    return _normalize(data)


def destroy_instance(instance_id) -> bool:
    try:
        response = _request('DELETE', f'/pods/{instance_id}')
    except RunpodError as exc:
        logger.warning('destroy_instance %s: %s', instance_id, exc)
        return False
    return 200 <= response.status_code < 300 or response.status_code == 404


def derive_base_url(instance: dict, container_port: int):
    if (instance and instance.get('actual_status') == 'running'
            and instance.get('instance_id')):
        return f'https://{instance["instance_id"]}-{container_port}.proxy.runpod.net'
    return None
