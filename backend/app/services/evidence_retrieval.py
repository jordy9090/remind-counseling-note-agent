"""Dense-only raw evidence retrieval with deterministic diversification."""
from __future__ import annotations

from collections import Counter
from typing import Any

from app.schemas.evidence import EvidenceSet, RetrievedEvidenceEpisode
from app.services.embeddings import embed_query
from app.services.supabase_storage import storage


def retrieve_evidence_episodes(
    *, query_text: str, user_id: str, case_id: str,
    episode_types: list[str] | None = None, candidate_k: int = 12,
) -> list[RetrievedEvidenceEpisode]:
    if not query_text.strip() or not user_id.strip() or not case_id.strip():
        return []
    rows = storage.rpc("match_evidence_episodes", {
        "query_embedding": embed_query(query_text), "filter_user_id": user_id,
        "filter_case_id": case_id, "filter_episode_types": episode_types,
        "match_count": candidate_k,
    })
    return [RetrievedEvidenceEpisode.model_validate(row) for row in rows or []]


def retrieve_evidence_set(
    *, query_text: str, user_id: str, case_id: str, episode_types: list[str] | None = None,
    candidate_k: int = 12, max_results: int = 5, max_per_session: int = 2,
) -> EvidenceSet:
    candidates = retrieve_evidence_episodes(
        query_text=query_text, user_id=user_id, case_id=case_id,
        episode_types=episode_types, candidate_k=candidate_k,
    )
    return EvidenceSet(
        query_text=query_text, candidates=candidates,
        results=diversify_evidence_episodes(candidates, max_results=max_results, max_per_session=max_per_session),
    )


def span_overlap_ratio(left: RetrievedEvidenceEpisode, right: RetrievedEvidenceEpisode) -> float:
    if left.session_id != right.session_id:
        return 0.0
    intersection = max(0, min(left.end_turn_index, right.end_turn_index) - max(left.start_turn_index, right.start_turn_index) + 1)
    shorter = min(left.end_turn_index - left.start_turn_index + 1, right.end_turn_index - right.start_turn_index + 1)
    return intersection / shorter if shorter else 0.0


def diversify_evidence_episodes(
    candidates: list[RetrievedEvidenceEpisode], *, max_results: int = 5,
    max_per_session: int = 2, overlap_threshold: float = 0.7,
    type_diversity_max_score_drop: float = 0.05,
) -> list[RetrievedEvidenceEpisode]:
    if max_results <= 0 or max_per_session <= 0:
        return []
    selected: list[RetrievedEvidenceEpisode] = []
    seen: set[tuple[str, str]] = set()
    session_counts: Counter[str] = Counter()
    for candidate in candidates:
        duplicate_key = (candidate.source_ref, candidate.episode_type)
        if duplicate_key in seen or session_counts[candidate.session_id] >= max_per_session:
            continue
        if any(span_overlap_ratio(candidate, current) >= overlap_threshold for current in selected):
            continue
        seen.add(duplicate_key)
        session_counts[candidate.session_id] += 1
        selected.append(candidate)
        if len(selected) == max_results:
            break

    present_types = {item.episode_type for item in selected}
    available_types = {item.episode_type for item in candidates}
    if len(selected) == max_results and len(present_types) == 1 and len(available_types) > 1:
        boundary_score = selected[-1].similarity_score
        for candidate in candidates:
            if candidate.episode_type in present_types or boundary_score - candidate.similarity_score > type_diversity_max_score_drop:
                continue
            tentative = selected[:-1]
            if sum(item.session_id == candidate.session_id for item in tentative) >= max_per_session:
                continue
            if any(span_overlap_ratio(candidate, current) >= overlap_threshold for current in tentative):
                continue
            selected[-1] = candidate
            break
    return selected
