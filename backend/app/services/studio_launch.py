"""Shared cell-expansion and launch orchestration for Studio run modes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from .studio_cells import EffectiveStudioCell

MatrixCell = tuple[str, float, str, float | None, int | None, int | None]


@dataclass(frozen=True)
class LaunchSubject:
    dataset_id: int
    trigger_word: str | None
    prompt: str
    checkpoint: str | None
    allowed: frozenset[str]
    training_run_record_id: int | None


@dataclass(frozen=True)
class LaunchOptions:
    family: str
    run_seed: int
    models: tuple[str | None, ...]
    seeds: tuple[int, ...]
    batch_loras: tuple[dict[str, Any] | None, ...]
    knobs: dict[str, Any]
    rebalance: float | None
    run_id: str | None = None


def launch_matrix(
    subjects: Iterable[LaunchSubject],
    options: LaunchOptions,
    *,
    cells_for: Callable[[LaunchSubject], Iterable[MatrixCell]],
    dimensions: Callable[[str, str, str | None], tuple[int, int]],
    launch: Callable[[EffectiveStudioCell, set[str]], Any],
    on_error: Callable[[Exception, int], Exception] | None = None,
) -> list[int]:
    """Expand every run axis once and launch each immutable effective cell.

    Dataset and comparison runs provide only their subjects and matrix source;
    persistence/workflow field propagation and nesting order are identical.
    """
    identifiers: list[int] = []
    for subject in subjects:
        for model in options.models:
            for checkpoint, strength, aspect, cfg, steps, steps2 in cells_for(subject):
                width, height = dimensions(
                    aspect, options.family, options.knobs.get("resolution_tier"))
                for batch_lora in options.batch_loras:
                    persisted = ([{**batch_lora, "batch": True}] if batch_lora else [])
                    workflow = ([batch_lora] if batch_lora else [])
                    for seed in options.seeds:
                        cell = EffectiveStudioCell(
                            checkpoint=checkpoint,
                            strength=strength,
                            seed=seed,
                            run_seed=options.run_seed,
                            run_id=options.run_id,
                            z_model=model,
                            aspect=aspect,
                            prompt=subject.prompt,
                            cfg=cfg,
                            steps=steps,
                            steps2=steps2,
                            family=options.family,
                            width=width,
                            height=height,
                            dataset_id=subject.dataset_id,
                            trigger_word=subject.trigger_word,
                            extra_loras=tuple(options.knobs["extra_loras"] + workflow),
                            persisted_extra_loras=tuple(
                                options.knobs["extra_loras"] + persisted),
                            krea_rebalance=options.rebalance,
                            negative=options.knobs["negative"],
                            sampler=options.knobs["sampler"],
                            scheduler=options.knobs["scheduler"],
                            weight_dtype=options.knobs["weight_dtype"],
                            enhancer_strength=options.knobs["enhancer_strength"],
                            detail_amount=options.knobs["detail_amount"],
                            resolution_tier=options.knobs["resolution_tier"],
                            init_image=options.knobs["init_image"],
                            denoise=options.knobs["denoise"],
                            training_run_record_id=subject.training_run_record_id,
                        )
                        try:
                            row = launch(cell, set(subject.allowed))
                        except Exception as error:
                            if on_error is not None:
                                raise on_error(error, len(identifiers)) from error
                            raise
                        identifiers.append(row.id)
    return identifiers
