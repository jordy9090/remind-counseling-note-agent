"""Simple JSON-backed storage for temporary counseling note drafts."""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.core.config import settings
from app.schemas.note import (
    TemporaryDraftRecord,
    TemporaryDraftSaveRequest,
    TemporaryDraftSaveResponse,
)
from app.services import supabase_store


SAFE_DRAFT_ID = re.compile(r"^[A-Za-z0-9_-]{8,80}$")


def save_temporary_draft(request: TemporaryDraftSaveRequest, *, actor: str) -> TemporaryDraftSaveResponse:
    """Create or update a temporary draft record."""
    draft_id = request.draft_id if _is_safe_draft_id(request.draft_id) else _new_draft_id()
    saved_at = datetime.now(UTC).isoformat()
    data = request.model_dump()
    data["draft_id"] = draft_id
    data["saved_at"] = saved_at
    record = TemporaryDraftRecord(**data)

    if supabase_store.configured_for(actor):
        supabase_store.upsert_draft_row(record, actor=actor)
    else:
        _write_to_disk(record, actor=actor)

    return TemporaryDraftSaveResponse(
      draft_id=draft_id,
      case_id=record.case_id,
      session_number=record.session_number,
      saved_at=saved_at,
    )


def get_temporary_draft(draft_id: str, *, actor: str) -> TemporaryDraftRecord | None:
    """Load a temporary draft by id."""
    if not _is_safe_draft_id(draft_id):
        return None
    if supabase_store.configured_for(actor):
        return supabase_store.get_draft_row(draft_id, actor=actor)
    path = _draft_path(draft_id, actor=actor)
    if not path.exists():
        return None
    return TemporaryDraftRecord(**json.loads(path.read_text(encoding="utf-8")))


def list_temporary_drafts(*, actor: str, case_id: str | None = None) -> list[TemporaryDraftRecord]:
    """List saved temporary drafts, newest first."""
    if supabase_store.configured_for(actor):
        return supabase_store.list_draft_rows(actor=actor, case_id=case_id)
    records: list[TemporaryDraftRecord] = []
    for path in _draft_dir(actor).glob("*.json"):
        try:
            record = TemporaryDraftRecord(**json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
        if case_id and record.case_id != case_id:
            continue
        records.append(record)
    return sorted(records, key=lambda record: record.saved_at, reverse=True)


def _write_to_disk(record: TemporaryDraftRecord, *, actor: str) -> None:
    """Persist a draft record to the local filesystem (Supabase 미설정 시 폴백)."""
    path = _draft_path(record.draft_id, actor=actor)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(
        json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(path)


def _draft_dir(actor: str) -> Path:
    configured_dir = os.getenv("TEMP_DRAFT_DIR")
    if configured_dir:
        base = Path(configured_dir)
    else:
        base = Path(tempfile.gettempdir()) / "remind-counseling-note-agent" / "drafts"
    safe_actor = re.sub(r"[^A-Za-z0-9_-]", "_", actor)[:80] or "unknown"
    return base / safe_actor


def _draft_path(draft_id: str, *, actor: str) -> Path:
    return _draft_dir(actor) / f"{draft_id}.json"


def _new_draft_id() -> str:
    return f"draft_{uuid4().hex}"


def _is_safe_draft_id(draft_id: str | None) -> bool:
    return bool(draft_id and SAFE_DRAFT_ID.fullmatch(draft_id))
