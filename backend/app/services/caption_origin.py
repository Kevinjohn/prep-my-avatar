"""Atomic caption text, authorship, and provenance mutations."""

from __future__ import annotations

from sqlalchemy import func, or_

ASSERTED = "asserted"
JOYCAPTION = "joycaption"
OLLAMA = "ollama"
ENGINES = (JOYCAPTION, OLLAMA)
ORIGINS = (ASSERTED, *ENGINES)


def engine_origin(engine: str | None) -> str | None:
    """Return a persisted origin only for a resolved captioning engine."""
    normalized = str(engine or "").strip().lower()
    return normalized if normalized in ENGINES else None


def set_caption(
    row,
    text: str | None,
    *,
    origin: str | None,
    provenance: str | None = None,
):
    """Replace a row's complete caption tuple without retaining stale metadata."""
    if origin is not None and origin not in ORIGINS:
        raise ValueError(f"unsupported caption origin: {origin}")
    has_text = bool(str(text or "").strip())
    row.caption = text
    row.caption_origin = origin if has_text else None
    row.caption_provenance = provenance if has_text else None
    return row


def set_human_caption(row, text: str | None):
    """Store user-authored text and discard provenance from any prior model text."""
    return set_caption(row, text, origin=ASSERTED)


def set_model_caption(
    row,
    text: str | None,
    *,
    engine: str | None,
    provenance: str | None = None,
):
    """Store model text with the actual engine, never an unresolved policy name."""
    origin = engine_origin(engine)
    return set_caption(
        row,
        text,
        origin=origin,
        provenance=provenance if origin == JOYCAPTION else None,
    )


def unprotected_clause(model):
    """Select blank, machine, and legacy-unknown captions using SQL NULL semantics."""
    text = model.caption
    origin = model.caption_origin
    return or_(
        text.is_(None),
        func.trim(text) == "",
        origin.is_(None),
        origin != ASSERTED,
    )
