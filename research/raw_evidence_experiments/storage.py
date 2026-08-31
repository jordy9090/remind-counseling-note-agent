"""Episode-table helpers retained only for reproducible research comparisons."""
from __future__ import annotations

from collections.abc import Iterable

from app.core.config import settings
from app.schemas.evidence import StoredTranscriptTurn, TranscriptTurn
from app.services.embeddings import content_hash
from app.services.supabase_storage import storage
from app.services.transcript_storage import (
    TranscriptStorageError,
    build_transcript_source_ref,
    build_transcript_span_text,
    get_transcript_turns,
    store_transcript_turns,
)
from research.raw_evidence_experiments.schemas import EvidenceEpisode, EvidenceEpisodeSpan


def create_evidence_episode_from_span(
    *, user_id: str, counselor_id: str, case_id: str, session_id: str, span: EvidenceEpisodeSpan,
) -> EvidenceEpisode:
    if not all(value.strip() for value in (user_id, counselor_id, case_id, session_id)):
        raise ValueError("user_id, counselor_id, case_id, and session_id are required")
    if user_id != counselor_id:
        raise TranscriptStorageError("counselor_id must match the authenticated user scope")
    turns = get_transcript_turns(user_id=user_id, case_id=case_id, session_id=session_id)
    validate_episode_role_feasibility(span, turns)
    episode_text = build_transcript_span_text(turns, span.start_turn_index, span.end_turn_index)
    source_ref = build_transcript_source_ref(session_id, span.start_turn_index, span.end_turn_index)
    row = {
        "user_id": user_id,
        "counselor_id": counselor_id,
        "case_id": case_id,
        "session_id": session_id,
        **span.model_dump(mode="json"),
        "source_ref": source_ref,
        "episode_text": episode_text,
        "content_hash": content_hash(episode_text, model=settings.embedding_model),
    }
    stored = storage.upsert(
        "evidence_episodes", [row], on_conflict="session_id,start_turn_index,end_turn_index,episode_type",
    )
    if not stored:
        raise TranscriptStorageError("Evidence episode storage returned no row")
    return EvidenceEpisode.model_validate(stored[0])


def validate_episode_role_feasibility(
    span: EvidenceEpisodeSpan,
    turns: Iterable[TranscriptTurn | StoredTranscriptTurn],
) -> None:
    scoped = [turn for turn in turns if span.start_turn_index <= turn.turn_index <= span.end_turn_index]
    roles = {turn.speaker_role for turn in scoped}
    if span.episode_type == "intervention_response" and not {"counselor", "client"} <= roles:
        raise ValueError("intervention_response span requires at least one counselor and one client turn")
    if span.episode_type == "client_event_state" and "client" not in roles:
        raise ValueError("client_event_state span requires at least one client turn")
