"""Immutable effective local-training job contract.

Resolution/validation remains in the training domain service. Once values are
effective, this object is the one propagation boundary for direct launches,
continuations, queued/scheduled persistence, and queue replay.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EffectiveTrainingJob:
    user_id: str
    dataset_id: int
    steps: int | None = None
    extra_steps: int | None = None
    check_captions: bool = True
    base_model: Any = None
    variant: str | None = None
    train_type: str | None = None
    allow_caption_mismatch: bool = False
    masked: bool = True
    fresh: bool = False
    allow_uncaptioned: bool = False
    vae_path: Any = None
    te_path: Any = None
    allow_unverified_weights: bool = False
    not_before: str | None = None
    job_id: str | None = None

    @property
    def continuation(self) -> bool:
        return bool(self.extra_steps)

    def launch_kwargs(self) -> dict[str, Any]:
        return {
            'user_id': self.user_id,
            'dataset_id': self.dataset_id,
            'steps': self.steps,
            'check_captions': self.check_captions,
            'base_model': self.base_model,
            'variant': self.variant,
            'train_type': self.train_type,
            'allow_caption_mismatch': self.allow_caption_mismatch,
            'masked': self.masked,
            'fresh': self.fresh,
            'allow_uncaptioned': self.allow_uncaptioned,
            'vae_path': self.vae_path,
            'te_path': self.te_path,
            'allow_unverified_weights': self.allow_unverified_weights,
        }

    def continuation_kwargs(self) -> dict[str, Any]:
        return {
            'user_id': self.user_id,
            'dataset_id': self.dataset_id,
            'extra_steps': self.extra_steps,
            'base_model': self.base_model,
            'variant': self.variant,
            'train_type': self.train_type,
            'masked': self.masked,
            'fresh': self.fresh,
            'allow_caption_mismatch': self.allow_caption_mismatch,
            'allow_uncaptioned': self.allow_uncaptioned,
            'vae_path': self.vae_path,
            'te_path': self.te_path,
            'allow_unverified_weights': self.allow_unverified_weights,
        }

    def queue_record(self) -> dict[str, Any]:
        return {
            'id': self.job_id,
            'dataset_id': self.dataset_id,
            'user_id': self.user_id,
            'extra_steps': self.extra_steps,
            'base_model': self.base_model,
            'variant': self.variant,
            'train_type': self.train_type,
            'not_before': self.not_before,
            'masked': self.masked,
            'steps': self.steps,
            'fresh': self.fresh,
            'vae_path': self.vae_path,
            'te_path': self.te_path,
            'allow_unverified_weights': self.allow_unverified_weights,
            'allow_caption_mismatch': self.allow_caption_mismatch,
            'allow_uncaptioned': self.allow_uncaptioned,
        }

    @classmethod
    def from_queue_record(cls, item: dict[str, Any], *, persisted: Any) \
            -> 'EffectiveTrainingJob':
        return cls(
            job_id=item.get('id'),
            user_id=item.get('user_id'),
            dataset_id=item['dataset_id'],
            extra_steps=item.get('extra_steps'),
            base_model=item.get('base_model'),
            variant=item.get('variant'),
            train_type=item.get('train_type'),
            not_before=item.get('not_before'),
            masked=item.get('masked', True),
            steps=item.get('steps'),
            fresh=bool(item.get('fresh')),
            vae_path=item.get('vae_path', persisted),
            te_path=item.get('te_path', persisted),
            allow_unverified_weights=bool(item.get('allow_unverified_weights')),
            allow_caption_mismatch=bool(item.get('allow_caption_mismatch')),
            allow_uncaptioned=bool(item.get('allow_uncaptioned')),
        )
