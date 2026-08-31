"""Standalone raw-window retrieval and query-conditioned selection candidate pipeline."""
from __future__ import annotations

from app.schemas.evidence import EvidenceExtractionDiagnostic, RawEvidenceSelectionSet
from app.services.evidence_storage import get_transcript_turns
from app.services.query_evidence_selection import select_evidence_spans_with_diagnostics
from app.services.raw_evidence_retrieval import (
    DEFAULT_WINDOW_CANDIDATE_K, build_candidate_regions, retrieve_transcript_window_candidates,
)


def retrieve_query_conditioned_raw_evidence(
    *, query_text: str, user_id: str, case_id: str,
    candidate_k: int = DEFAULT_WINDOW_CANDIDATE_K, max_results: int = 5,
) -> RawEvidenceSelectionSet:
    """Offline/standalone PR2.8 path; deliberately not connected to generation or LangGraph."""
    candidates = retrieve_transcript_window_candidates(
        query_text=query_text, user_id=user_id, case_id=case_id, candidate_k=candidate_k,
    )
    regions = build_candidate_regions(windows=candidates, user_id=user_id, case_id=case_id)
    selected = []
    diagnostics: list[EvidenceExtractionDiagnostic] = []
    seen_source_refs = set()
    for region in regions:
        turns = get_transcript_turns(user_id=user_id, case_id=case_id, session_id=region.session_id)
        region_turns = [
            turn for turn in turns if region.start_turn_index <= turn.turn_index <= region.end_turn_index
        ]
        spans, span_diagnostics = select_evidence_spans_with_diagnostics(
            query_text=query_text, region_turns=region_turns,
            session_number=region.session_number, retrieval_score=region.retrieval_score,
            retrieval_rank=region.retrieval_rank,
        )
        diagnostics.extend(span_diagnostics)
        for span in spans:
            if span.source_ref in seen_source_refs:
                continue
            seen_source_refs.add(span.source_ref)
            selected.append(span)
    selected.sort(key=lambda item: (
        item.retrieval_rank if item.retrieval_rank is not None else 10**9,
        -(item.retrieval_score if item.retrieval_score is not None else -1.0),
        item.session_id, item.start_turn_index,
    ))
    return RawEvidenceSelectionSet(
        query_text=query_text, candidates=candidates, regions=regions,
        results=selected[:max(max_results, 0)], diagnostics=diagnostics,
    )
