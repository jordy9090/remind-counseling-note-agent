"""Cached recomposition for checklist-specific AI note drafts."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from threading import Lock

from app.core.config import settings
from app.graph.graph import run_note_pipeline
from app.schemas.note import GenerateNoteResponse, RecomposeNoteRequest, RecomposeNoteResponse


CACHE_VERSION = "recompose-v4-summary-quality"
_CACHE_REPLACE_LOCK = Lock()


def recompose_note_with_cache(request: RecomposeNoteRequest, *, actor: str = "") -> RecomposeNoteResponse:
    """Return a checklist-specific generated note, using cache for repeated settings."""
    actor_id = str(actor or settings.remind_preview_actor)
    visible_section_ids = _normalize_section_ids(request.visible_section_ids)
    cache_key = build_recompose_cache_key(request, visible_section_ids, actor=actor_id)
    cached = _read_cached_result(cache_key)
    if cached is not None:
        return RecomposeNoteResponse(
            result=cached,
            visible_section_ids=visible_section_ids,
            cache_key=cache_key,
            cache_hit=True,
        )

    result = run_note_pipeline(
        request.session_input,
        requested_section_ids=visible_section_ids,
        session_topic=request.session_topic,
        actor=actor,
    )
    _write_cached_result(cache_key, result)
    return RecomposeNoteResponse(
        result=result,
        visible_section_ids=visible_section_ids,
        cache_key=cache_key,
        cache_hit=False,
    )


def build_recompose_cache_key(
    request: RecomposeNoteRequest,
    visible_section_ids: list[str] | None = None,
    *,
    actor: str = "",
) -> str:
    payload = {
        "version": CACHE_VERSION,
        "use_stub": settings.use_stub,
        "model": settings.openai_model,
        "model_configured": bool(settings.openai_api_key),
        "actor": str(actor or settings.remind_preview_actor),
        "enable_rag": settings.enable_rag,
        "enable_raw_region_grounding": settings.enable_raw_region_grounding,
        "actor_scope": actor or settings.remind_preview_actor,
        "session_input": request.session_input.model_dump(mode="json"),
        "session_topic": request.session_topic,
        "visible_section_ids": visible_section_ids or _normalize_section_ids(request.visible_section_ids),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize_section_ids(section_ids: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for section_id in section_ids:
        if section_id in seen:
            continue
        seen.add(section_id)
        normalized.append(section_id)
    return normalized


def _read_cached_result(cache_key: str) -> GenerateNoteResponse | None:
    path = _cache_path(cache_key)
    if not path.exists():
        return None
    try:
        return GenerateNoteResponse(**json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return None


def _write_cached_result(cache_key: str, result: GenerateNoteResponse) -> None:
    path = _cache_path(cache_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2)
    temp_path: Path | None = None
    try:
        # Separate staging files prevent concurrent requests sharing a partial result.
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False,
            prefix=f".{cache_key}.", suffix=".tmp", dir=path.parent,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(payload)
        # Close before replacement so the same path also works on Windows.
        # Windows can reject simultaneous replacement of the same destination.
        with _CACHE_REPLACE_LOCK:
            temp_path.replace(path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _cache_dir() -> Path:
    configured_dir = os.getenv("RECOMPOSE_CACHE_DIR")
    if configured_dir:
        return Path(configured_dir)
    return Path(tempfile.gettempdir()) / "remind-counseling-note-agent" / "recompose-cache"


def _cache_path(cache_key: str) -> Path:
    return _cache_dir() / f"{cache_key}.json"
