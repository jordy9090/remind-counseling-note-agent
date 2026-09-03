"""Production storage helpers for sanitized transcript turns and exact spans."""
from __future__ import annotations

from typing import Any, Iterable

from app.schemas.evidence import StoredTranscriptTurn, TranscriptTurn
from app.services.deidentification import deidentify_text
from app.services.supabase_storage import SupabaseStorage, storage


class TranscriptStorageError(RuntimeError):
    pass


def build_transcript_source_ref(session_id: str, start_turn_index: int, end_turn_index: int) -> str:
    if not session_id or start_turn_index < 0 or end_turn_index < start_turn_index:
        raise ValueError("A session id and a valid inclusive turn span are required")
    return f"transcript:{session_id}:{start_turn_index}-{end_turn_index}"


def build_transcript_span_text(
    turns: Iterable[TranscriptTurn | StoredTranscriptTurn | dict[str, Any]],
    start_turn_index: int,
    end_turn_index: int,
) -> str:
    if start_turn_index < 0 or end_turn_index < start_turn_index:
        raise ValueError("Invalid inclusive turn span")
    normalized = [turn if isinstance(turn, (TranscriptTurn, StoredTranscriptTurn)) else TranscriptTurn.model_validate(turn) for turn in turns]
    by_index: dict[int, TranscriptTurn | StoredTranscriptTurn] = {}
    for turn in normalized:
        if turn.turn_index in by_index:
            raise ValueError(f"Duplicate transcript turn index: {turn.turn_index}")
        by_index[turn.turn_index] = turn
    expected = list(range(start_turn_index, end_turn_index + 1))
    missing = [index for index in expected if index not in by_index]
    if missing:
        raise ValueError(f"Missing transcript turns in requested span: {missing}")
    # No rewriting or summarization: stored sanitized_text is copied verbatim.
    return "\n".join(f"[{by_index[index].speaker_role}] {by_index[index].sanitized_text}" for index in expected)


def store_transcript_turns(
    *,
    user_id: str,
    counselor_id: str,
    case_id: str,
    session_id: str,
    turns: list[TranscriptTurn],
    storage_client: SupabaseStorage | None = None,
) -> list[StoredTranscriptTurn]:
    client = storage_client or storage
    _require_scope(user_id=user_id, counselor_id=counselor_id, case_id=case_id, session_id=session_id)
    _assert_scoped_session(user_id=user_id, case_id=case_id, session_id=session_id, storage_client=client)
    if len({turn.turn_index for turn in turns}) != len(turns):
        raise ValueError("Transcript turns must have unique turn_index values")
    rows = []
    for turn in turns:
        sanitized_text = deidentify_text(turn.sanitized_text, source=f"transcript.turn_{turn.turn_index}")[0]
        if not sanitized_text.strip():
            raise ValueError(f"Transcript turn {turn.turn_index} is empty after sanitization")
        rows.append({
            "user_id": user_id, "counselor_id": counselor_id, "case_id": case_id, "session_id": session_id,
            **turn.model_dump(mode="json"), "sanitized_text": sanitized_text,
        })
    stored = client.upsert("transcript_turns", rows, on_conflict="session_id,turn_index") if rows else []
    return [StoredTranscriptTurn.model_validate(row) for row in stored]


def get_transcript_turns(
    *,
    user_id: str,
    case_id: str,
    session_id: str,
    storage_client: SupabaseStorage | None = None,
) -> list[StoredTranscriptTurn]:
    client = storage_client or storage
    _require_scope(user_id=user_id, counselor_id=user_id, case_id=case_id, session_id=session_id)
    rows = client.select("transcript_turns", {
        "user_id": f"eq.{user_id}", "case_id": f"eq.{case_id}", "session_id": f"eq.{session_id}",
        "select": "id,user_id,counselor_id,case_id,session_id,turn_index,speaker_role,start_ms,end_ms,sanitized_text,source_type,metadata_json",
        "order": "turn_index.asc", "limit": 10000,
    })
    return sorted((StoredTranscriptTurn.model_validate(row) for row in rows), key=lambda turn: turn.turn_index)


def _assert_scoped_session(
    *,
    user_id: str,
    case_id: str,
    session_id: str,
    storage_client: SupabaseStorage,
) -> None:
    session = storage_client.maybe_single("sessions", {
        "id": f"eq.{session_id}", "user_id": f"eq.{user_id}", "case_id": f"eq.{case_id}",
        "select": "id,user_id,case_id", "limit": 1,
    })
    if session is None:
        raise TranscriptStorageError("Session was not found inside the requested user/case scope")


def _require_scope(*, user_id: str, counselor_id: str, case_id: str, session_id: str) -> None:
    if not all(value.strip() for value in (user_id, counselor_id, case_id, session_id)):
        raise ValueError("user_id, counselor_id, case_id, and session_id are required")
    if user_id != counselor_id:
        raise TranscriptStorageError("counselor_id must match the authenticated user scope")
