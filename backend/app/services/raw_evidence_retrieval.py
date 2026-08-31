"""Dense raw-window retrieval and deterministic candidate-region construction."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from app.schemas.evidence import CandidateTranscriptRegion, RetrievedTranscriptWindow, StoredTranscriptTurn
from app.services.embeddings import embed_query
from app.services.transcript_storage import (
    build_transcript_source_ref,
    build_transcript_span_text,
    get_transcript_turns,
)
from app.services.supabase_storage import storage


DEFAULT_WINDOW_CANDIDATE_K = 12
CONTEXT_EXPANSION_TURNS = 2
TurnLoader = Callable[..., list[StoredTranscriptTurn]]


def retrieve_transcript_window_candidates(
    *, query_text: str, user_id: str, case_id: str, candidate_k: int = DEFAULT_WINDOW_CANDIDATE_K,
) -> list[RetrievedTranscriptWindow]:
    if not query_text.strip() or not user_id.strip() or not case_id.strip() or candidate_k <= 0:
        return []
    rows = storage.rpc("match_transcript_windows", {
        "query_embedding": embed_query(query_text), "filter_user_id": user_id,
        "filter_case_id": case_id, "match_count": candidate_k,
    })
    return [RetrievedTranscriptWindow.model_validate(row) for row in rows or []]


def build_candidate_regions(
    *, windows: list[RetrievedTranscriptWindow], user_id: str, case_id: str,
    context_expansion: int = CONTEXT_EXPANSION_TURNS,
    turn_loader: TurnLoader = get_transcript_turns,
) -> list[CandidateTranscriptRegion]:
    if context_expansion < 0:
        raise ValueError("context_expansion must be non-negative")
    ranked = list(enumerate(windows, start=1))
    by_session = defaultdict(list)
    for rank, window in ranked:
        by_session[window.session_id].append((rank, window))

    regions = []
    for session_id, session_windows in by_session.items():
        session_windows.sort(key=lambda item: (item[1].start_turn_index, item[1].end_turn_index))
        merged = []
        for rank, window in session_windows:
            if not merged or window.start_turn_index > merged[-1]["end"] + 1:
                merged.append({
                    "start": window.start_turn_index, "end": window.end_turn_index,
                    "rank": rank, "score": window.similarity_score,
                    "session_number": window.session_number, "ids": [window.window_id],
                })
            else:
                current = merged[-1]
                current["end"] = max(current["end"], window.end_turn_index)
                current["rank"] = min(current["rank"], rank)
                current["score"] = max(current["score"], window.similarity_score)
                current["ids"].append(window.window_id)

        turns = turn_loader(user_id=user_id, case_id=case_id, session_id=session_id)
        if not turns:
            continue
        ordered = sorted(turns, key=lambda item: item.turn_index)
        lower, upper = ordered[0].turn_index, ordered[-1].turn_index
        for item in merged:
            start = max(lower, item["start"] - context_expansion)
            end = min(upper, item["end"] + context_expansion)
            text = build_transcript_span_text(ordered, start, end)
            regions.append(CandidateTranscriptRegion(
                session_id=session_id, session_number=item["session_number"],
                start_turn_index=start, end_turn_index=end, region_text=text,
                source_ref=build_transcript_source_ref(session_id, start, end),
                retrieval_score=item["score"], retrieval_rank=item["rank"], window_ids=item["ids"],
            ))
    return sorted(regions, key=lambda item: (item.retrieval_rank, -item.retrieval_score, item.session_id))
