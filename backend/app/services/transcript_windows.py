"""Deterministic transcript-window construction, storage, and embedding."""
from __future__ import annotations

from datetime import UTC, datetime

from app.core.config import settings
from app.schemas.evidence import StoredTranscriptTurn, TranscriptWindow
from app.services.embeddings import content_hash, get_embedding_provider
from app.services.transcript_storage import build_transcript_span_text, get_transcript_turns
from app.services.supabase_storage import storage


WINDOW_SIZE_TURNS = 6
WINDOW_STRIDE_TURNS = 3


def build_transcript_window_source_ref(session_id: str, start_turn_index: int, end_turn_index: int) -> str:
    if not session_id or start_turn_index < 0 or end_turn_index < start_turn_index:
        raise ValueError("A session id and valid inclusive window span are required")
    return f"transcript_window:{session_id}:{start_turn_index}-{end_turn_index}"


def build_transcript_windows(
    turns: list[StoredTranscriptTurn], *, window_size: int = WINDOW_SIZE_TURNS,
    stride: int = WINDOW_STRIDE_TURNS,
) -> list[TranscriptWindow]:
    """Build fixed turn-count windows and an end-aligned terminal window."""
    if window_size <= 0 or stride <= 0:
        raise ValueError("window_size and stride must be positive")
    if not turns:
        return []
    ordered = sorted(turns, key=lambda item: item.turn_index)
    scope = (ordered[0].user_id, ordered[0].counselor_id, ordered[0].case_id, ordered[0].session_id)
    if any((item.user_id, item.counselor_id, item.case_id, item.session_id) != scope for item in ordered):
        raise ValueError("All transcript turns must share one user/case/session scope")
    indices = [item.turn_index for item in ordered]
    if len(set(indices)) != len(indices) or indices != list(range(indices[0], indices[-1] + 1)):
        raise ValueError("Transcript turns must have unique continuous turn indices")

    count = len(ordered)
    if count <= window_size:
        starts = [0]
    else:
        starts = list(range(0, count - window_size + 1, stride))
        terminal_start = count - window_size
        if starts[-1] != terminal_start:
            starts.append(terminal_start)

    windows = []
    for position in starts:
        selected = ordered[position:min(position + window_size, count)]
        start, end = selected[0].turn_index, selected[-1].turn_index
        text = build_transcript_span_text(ordered, start, end)
        windows.append(TranscriptWindow(
            user_id=scope[0], counselor_id=scope[1], case_id=scope[2], session_id=scope[3],
            start_turn_index=start, end_turn_index=end, window_text=text,
            source_ref=build_transcript_window_source_ref(scope[3], start, end),
            content_hash=content_hash(text, model=settings.embedding_model),
        ))
    return windows


def index_transcript_windows(
    *, user_id: str, counselor_id: str, case_id: str, session_id: str,
    window_size: int = WINDOW_SIZE_TURNS, stride: int = WINDOW_STRIDE_TURNS,
) -> tuple[list[TranscriptWindow], int]:
    turns = get_transcript_turns(user_id=user_id, case_id=case_id, session_id=session_id)
    windows = build_transcript_windows(turns, window_size=window_size, stride=stride)
    stored_windows: list[TranscriptWindow] = []
    embedded = 0
    for window in windows:
        row = window.model_dump(mode="json", exclude={"id", "embedding_model"})
        stored = storage.upsert(
            "transcript_windows", [row], on_conflict="session_id,start_turn_index,end_turn_index",
        )
        if not stored:
            raise RuntimeError("Transcript window storage returned no row")
        stored_window = TranscriptWindow.model_validate(stored[0])
        if ensure_transcript_window_embedding(stored[0]):
            embedded += 1
            stored_window = stored_window.model_copy(update={"embedding_model": settings.embedding_model})
        stored_windows.append(stored_window)
    return stored_windows, embedded


def ensure_transcript_window_embedding(window: dict) -> bool:
    existing = storage.maybe_single("transcript_windows", {
        "user_id": f'eq.{window["user_id"]}', "case_id": f'eq.{window["case_id"]}',
        "session_id": f'eq.{window["session_id"]}', "source_ref": f'eq.{window["source_ref"]}',
        "select": "id,content_hash,embedding_model,embedding", "limit": 1,
    })
    if (
        existing and existing.get("content_hash") == window["content_hash"]
        and existing.get("embedding_model") == settings.embedding_model and existing.get("embedding")
    ):
        return False
    vector = get_embedding_provider().embed([window["window_text"]])[0]
    storage.update("transcript_windows", {
        "embedding": vector, "embedding_model": settings.embedding_model,
        "embedding_updated_at": datetime.now(UTC).isoformat(),
    }, query={
        "user_id": f'eq.{window["user_id"]}', "case_id": f'eq.{window["case_id"]}',
        "session_id": f'eq.{window["session_id"]}', "source_ref": f'eq.{window["source_ref"]}',
    }, return_representation=False)
    return True
