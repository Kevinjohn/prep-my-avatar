"""Immutable effective Studio cell configuration.

This module is deliberately independent of Flask, SQLAlchemy, ComfyUI, and the
Studio service. It is the single field contract shared by new dataset grids,
comparison grids, persistence, workflow construction, and resume.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EffectiveStudioCell:
    checkpoint: str
    strength: float
    seed: int
    run_seed: int
    z_model: str | None
    aspect: str
    prompt: str
    cfg: float | None
    steps: int | None
    steps2: int | None
    family: str
    width: int
    height: int
    dataset_id: int
    trigger_word: str | None
    extra_loras: tuple[dict[str, Any], ...] = ()
    persisted_extra_loras: tuple[dict[str, Any], ...] | None = None
    krea_rebalance: float | None = None
    negative: str | None = None
    sampler: str | None = None
    scheduler: str | None = None
    weight_dtype: str | None = None
    enhancer_strength: float | None = None
    detail_amount: float | None = None
    resolution_tier: str | None = None
    init_image: str | None = None
    denoise: float | None = None
    run_id: str | None = None
    training_run_record_id: int | None = None

    def row_kwargs(self) -> dict[str, Any]:
        extra = list(self.persisted_extra_loras
                     if self.persisted_extra_loras is not None else self.extra_loras)
        return {
            'dataset_id': self.dataset_id,
            'checkpoint': self.checkpoint,
            'strength': self.strength,
            'seed': self.seed,
            'run_seed': self.run_seed,
            'run_id': self.run_id,
            'training_run_record_id': self.training_run_record_id,
            'status': 'pending',
            'z_model': self.z_model,
            'aspect': self.aspect,
            'prompt': self.prompt,
            'cfg': self.cfg,
            'steps': self.steps,
            'steps2': self.steps2,
            'extra_loras': json.dumps(extra) if extra else None,
            'krea_rebalance': self.krea_rebalance,
            'negative': self.negative,
            'sampler': self.sampler,
            'scheduler': self.scheduler,
            'weight_dtype': self.weight_dtype,
            'enhancer_strength': self.enhancer_strength,
            'detail_amount': self.detail_amount,
            'resolution_tier': self.resolution_tier,
            'init_image': self.init_image,
            'denoise': self.denoise,
        }

    def workflow_kwargs(self) -> dict[str, Any]:
        return {
            'width': self.width,
            'height': self.height,
            'cfg': self.cfg,
            'steps': self.steps,
            'steps2': self.steps2,
            'dataset_id': self.dataset_id,
            'train_type': self.family,
            'extra_loras': [dict(item) for item in self.extra_loras],
            'rebalance': self.krea_rebalance,
            'negative': self.negative,
            'sampler': self.sampler,
            'scheduler': self.scheduler,
            'weight_dtype': self.weight_dtype,
            'enhancer_strength': self.enhancer_strength,
            'detail_amount': self.detail_amount,
            'trigger_word': self.trigger_word,
        }

    @classmethod
    def from_row(cls, row, *, family: str, width: int, height: int,
                 z_model: str | None, prompt: str, seed: int,
                 trigger_word: str | None) -> 'EffectiveStudioCell':
        try:
            parsed = json.loads(row.extra_loras or '[]')
        except (TypeError, ValueError):
            parsed = []
        persisted_extras = tuple(item for item in parsed if isinstance(item, dict))
        extras = tuple(
            {key: value for key, value in item.items() if key != 'batch'}
            for item in persisted_extras
        )
        return cls(
            checkpoint=row.checkpoint,
            strength=row.strength,
            seed=seed,
            run_seed=row.run_seed or seed,
            z_model=z_model,
            aspect=row.aspect,
            prompt=prompt,
            cfg=row.cfg,
            steps=row.steps,
            steps2=row.steps2,
            family=family,
            width=width,
            height=height,
            dataset_id=row.dataset_id,
            trigger_word=trigger_word,
            extra_loras=extras,
            persisted_extra_loras=persisted_extras,
            krea_rebalance=row.krea_rebalance,
            negative=getattr(row, 'negative', None),
            sampler=getattr(row, 'sampler', None),
            scheduler=getattr(row, 'scheduler', None),
            weight_dtype=getattr(row, 'weight_dtype', None),
            enhancer_strength=getattr(row, 'enhancer_strength', None),
            detail_amount=getattr(row, 'detail_amount', None),
            resolution_tier=getattr(row, 'resolution_tier', None),
            init_image=getattr(row, 'init_image', None),
            denoise=getattr(row, 'denoise', None),
            run_id=row.run_id,
            training_run_record_id=row.training_run_record_id,
        )
