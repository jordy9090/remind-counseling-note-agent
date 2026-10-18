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
from app.graph.nodes import provider_safe_session_topic
from app.graph.summary_core import (
    AUTHENTICATED_FULL_POLICY,
    summary_request_context_budget_text,
    validate_summary_input_budget,
)
from app.schemas.note import GenerateNoteResponse, RecomposeNoteRequest, RecomposeNoteResponse
from app.services.supabase_storage import _storage_for_actor


# Older results did not validate their current confirmed-note sources.
CACHE_VERSION = "recompose-v6-confirmed-source-validity"
SOURCE_REVISION_LIMIT = 500
_CACHE_REPLACE_LOCK = Lock()


def recompose_note_with_cache(request: RecomposeNoteRequest, *, actor: str = "") -> RecomposeNoteResponse:
    """Return a checklist-specific generated note, using cache for repeated settings."""
    actor_id = str(actor or settings.remind_preview_actor)
    visible_section_ids = _normalize_section_ids(request.visible_section_ids)
    request_context_text = summary_request_context_budget_text(request.session_topic, visible_section_ids)
    validate_summary_input_budget(
        request.session_input,
        policy=AUTHENTICATED_FULL_POLICY,
        additional_input_text=request_context_text,
    )
    provider_session_topic = provider_safe_session_topic(
        request.session_topic,
        client_alias=request.session_input.client_alias,
        counselor_name=request.session_input.counselor_name,
    )
    if provider_session_topic != request.session_topic:
        validate_summary_input_budget(
            request.session_input,
            policy=AUTHENTICATED_FULL_POLICY,
            additional_input_text=summary_request_context_budget_text(
                provider_session_topic,
                visible_section_ids,
            ),
        )
    source_revision = _case_source_revision(request.session_input.case_id, actor=actor)
    cache_key = build_recompose_cache_key(request, visible_section_ids, actor=actor_id, source_revision=source_revision)
    cached = _read_cached_result(cache_key)
    if cached is not None:
        _assert_source_revision(request.session_input.case_id, actor=actor, expected=source_revision)
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
        input_budget_prevalidated=True,
    )
    _assert_source_revision(request.session_input.case_id, actor=actor, expected=source_revision)
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
    source_revision: str = "",
) -> str:
    payload = {
        "version": CACHE_VERSION,
        "use_stub": settings.use_stub,
        "llm_provider": settings.llm_provider,
        "model": settings.openai_model,
        "model_configured": settings.llm_configured,
        "actor": str(actor or settings.remind_preview_actor),
        "enable_rag": settings.enable_rag,
        "enable_raw_region_grounding": settings.enable_raw_region_grounding,
        "actor_scope": actor or settings.remind_preview_actor,
        "source_revision": source_revision,
        "session_input": request.session_input.model_dump(mode="json"),
        "session_topic": request.session_topic,
        "visible_section_ids": visible_section_ids or _normalize_section_ids(request.visible_section_ids),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _case_source_revision(case_id: str, *, actor: str) -> str:
    """Hash complete owned note sources without retaining their text in the key.

    The bound limits work, not the fingerprint's coverage: overflow fails closed
    instead of treating a truncated set or a maximum timestamp as a revision.
    """
    if not settings.enable_rag:
        return "rag-disabled"
    actor_id = str(actor or settings.remind_preview_actor)
    client = _storage_for_actor(actor)
    if not client.retrieval_enabled:
        return "retrieval-unconfigured"
    try:
        rows = []
        # An empty next page proves completion even if the service applies a
        # lower row cap than our requested limit. Never hash a partial snapshot.
        for _ in range(12):
            page = client.select("generated_notes", {
                "user_id": f"eq.{actor_id}", "case_id": f"eq.{case_id}",
                "select": "id,user_id,case_id,session_id,confirmation_status,confirmed_at,confirmed_json,draft_json,created_at,updated_at",
                "order": "id.asc", "limit": SOURCE_REVISION_LIMIT + 1, "offset": len(rows),
            })
            if not page:
                break
            rows.extend(page)
            if len(rows) > SOURCE_REVISION_LIMIT or any(
                row.get("user_id") != actor_id or row.get("case_id") != case_id for row in page
            ):
                raise ValueError("Incomplete or unscoped source snapshot")
        else:
            raise ValueError("Source pagination limit exceeded")
        if len({row.get("id") for row in rows}) != len(rows):
            raise ValueError("Source snapshot changed while paginating")
        payload = json.dumps(sorted(rows, key=lambda row: str(row.get("id") or "")),
                             ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        raise RuntimeError("Recomposition source validation is unavailable.") from None
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _assert_source_revision(case_id: str, *, actor: str, expected: str) -> None:
    if _case_source_revision(case_id, actor=actor) != expected:
        raise RuntimeError("Recomposition source changed during the request; retry with the current source.")


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
