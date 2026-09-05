"""Cloud provider metadata and durable per-run provider selection."""

import logging
from dataclasses import dataclass
from importlib import import_module

from .. import config as cfg

logger = logging.getLogger(__name__)


class ProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class Provider:
    name: str
    label: str
    secret: str
    supports_host_blacklist: bool

    @property
    def client(self):
        return import_module(f'.{self.name}_client', __package__)

    @property
    def ui_port(self):
        return self.boot_settings(cfg.get('cloud') or {})[1]

    def boot_settings(self, cloud):
        settings = cloud if self.name == 'vast' else cloud.get('runpod', {})
        template = (
            settings.get('template_hash' if self.name == 'vast' else 'template_id')
            or ''
        ).strip()
        port = int(settings.get('ui_port') or (18675 if self.name == 'vast' else 8675))
        if self.name == 'vast' and template and port == 8675:
            logger.warning(
                'cloud.ui_port=8675 is stale for template mode — using 18675'
            )
            port = 18675
        return template, port

    def console_url(self, iid=None):
        if self.name == 'vast':
            return 'https://cloud.vast.ai/instances/'
        return 'https://console.runpod.io/pods' + (f'/{iid}' if iid else '')


PROVIDERS = {
    'vast': Provider('vast', 'vast.ai', 'VAST_API_KEY', True),
    'runpod': Provider('runpod', 'RunPod', 'RUNPOD_API_KEY', False),
}


def _resolve(name):
    if name not in PROVIDERS:
        logger.warning('unknown cloud provider %r — using vast.ai', name)
        return PROVIDERS['vast']
    return PROVIDERS[name]


def current():
    return _resolve(cfg.get('cloud.provider') or 'vast')


def for_run(run):
    return _resolve(getattr(run, 'provider', None) or 'vast')


def configured():
    return [provider for provider in PROVIDERS.values() if cfg.secret(provider.secret)]
