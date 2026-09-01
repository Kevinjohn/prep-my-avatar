"""Atomic caption text, authorship, and provenance mutations."""

from __future__ import annotations

from sqlalchemy import and_, func, or_

ASSERTED = "asserted"
JOYCAPTION = "joycaption"
OLLAMA = "ollama"
OPENAI = "openai"
GEMINI = "gemini"
CHATGPT = "chatgpt"
ENGINES = (JOYCAPTION, OLLAMA, OPENAI, GEMINI, CHATGPT)
PROVENANCE_ENGINES = (JOYCAPTION, OPENAI, GEMINI, CHATGPT)
ORIGINS = (ASSERTED, *ENGINES)
CAPTION_FIELDS = ("caption", "caption_origin", "caption_provenance")


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


def caption_tuple(row) -> tuple[str | None, str | None, str | None]:
    """Return the complete concurrency token for one stored caption."""
    return row.caption, row.caption_origin, row.caption_provenance


def caption_tuple_clause(model, planned):
    """Build a NULL-safe SQL predicate for an exact planned caption tuple."""
    clauses = []
    for field, value in zip(CAPTION_FIELDS, planned, strict=True):
        column = getattr(model, field)
        clauses.append(column.is_(None) if value is None else column == value)
    return and_(*clauses)


def _normalize_text(text: str | None, max_chars: int | None = None) -> str | None:
    normalized = (text or "").strip()
    if max_chars is not None:
        normalized = normalized[:max_chars]
    return normalized or None


def set_human_caption(row, text: str | None, *, max_chars: int | None = None):
    """Store user-authored text and discard provenance from any prior model text."""
    return set_caption(row, _normalize_text(text, max_chars), origin=ASSERTED)


def clear_caption(row):
    """Clear caption text and every piece of metadata that describes it."""
    return set_caption(row, None, origin=None)


def copy_caption(target, source):
    """Copy an unchanged caption tuple between rows."""
    return set_caption(
        target,
        source.caption,
        origin=source.caption_origin,
        provenance=source.caption_provenance,
    )


def validate_replacement(find: str | None, mode: str = "text") -> str:
    """Validate and normalize one manual caption replacement request."""
    if mode not in ("text", "tag"):
        raise ValueError("invalid mode")
    normalized = (find or "").strip() if mode == "tag" else (find or "")
    if not normalized:
        raise ValueError("find is required")
    return normalized


def replace_human_caption(
    row,
    find: str,
    replacement: str | None,
    *,
    mode: str = "text",
    max_chars: int | None = None,
) -> bool:
    """Apply one manual text/tag replacement and stamp the resulting tuple."""
    find = validate_replacement(find, mode)
    old = row.caption or ""
    if mode == "text":
        new = old.replace(find, replacement or "")
    else:
        tags = [tag.strip() for tag in old.split(",")]
        out = []
        seen = set()
        for tag in tags:
            if not tag:
                continue
            new_tag = (
                (replacement or "").strip()
                if tag.lower() == find.lower()
                else tag
            )
            if not new_tag or new_tag.lower() in seen:
                continue
            seen.add(new_tag.lower())
            out.append(new_tag)
        new = ", ".join(out)
    new = _normalize_text(new, max_chars)
    if new == row.caption:
        return False
    set_human_caption(row, new, max_chars=max_chars)
    return True


def set_model_caption(
    row,
    text: str | None,
    *,
    engine: str | None,
    provenance: str | None = None,
):
    """Store model text with the actual engine, never an unresolved policy name."""
    values = model_caption_values(
        text,
        engine=engine,
        provenance=provenance,
    )
    for field, value in values.items():
        setattr(row, field, value)
    return row


def model_caption_values(
    text: str | None,
    *,
    engine: str | None,
    provenance: str | None = None,
) -> dict[str, str | None]:
    """Return the complete persisted tuple for one inference result."""
    origin = engine_origin(engine)
    has_text = bool(str(text or "").strip())
    return {
        "caption": text,
        "caption_origin": origin if has_text else None,
        "caption_provenance": (
            provenance if has_text and origin in PROVENANCE_ENGINES else None),
    }


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
