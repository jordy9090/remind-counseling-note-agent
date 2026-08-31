"""Query-conditioned source-span selection over deterministic raw candidate regions."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from app.core.config import settings
from app.schemas.evidence import StoredTranscriptTurn
from app.services.llm import get_llm
from app.services.transcript_storage import build_transcript_source_ref, build_transcript_span_text
from research.raw_evidence_experiments.schemas import (
    EvidenceExtractionDiagnostic,
    EvidenceSpanSelection,
    EvidenceSpanSelectionPayload,
    SelectedEvidenceSpan,
)


SpanSelector = Callable[[str, list[StoredTranscriptTurn]], EvidenceSpanSelectionPayload | dict[str, Any]]


def select_evidence_spans(
    *, query_text: str, region_turns: list[StoredTranscriptTurn], selector: SpanSelector | None = None,
    session_number: int | None = None, retrieval_score: float | None = None,
    retrieval_rank: int | None = None,
) -> list[SelectedEvidenceSpan]:
    spans, _ = select_evidence_spans_with_diagnostics(
        query_text=query_text, region_turns=region_turns, selector=selector,
        session_number=session_number, retrieval_score=retrieval_score, retrieval_rank=retrieval_rank,
    )
    return spans


def select_evidence_spans_with_diagnostics(
    *, query_text: str, region_turns: list[StoredTranscriptTurn], selector: SpanSelector | None = None,
    session_number: int | None = None, retrieval_score: float | None = None,
    retrieval_rank: int | None = None,
) -> tuple[list[SelectedEvidenceSpan], list[EvidenceExtractionDiagnostic]]:
    if not query_text.strip() or not region_turns:
        return [], []
    ordered = sorted(region_turns, key=lambda item: item.turn_index)
    scope = (ordered[0].user_id, ordered[0].case_id, ordered[0].session_id)
    if any((item.user_id, item.case_id, item.session_id) != scope for item in ordered):
        raise ValueError("Candidate region turns must share one user/case/session scope")
    by_index = {item.turn_index: item for item in ordered}
    raw = selector(query_text, ordered) if selector else _invoke_query_span_selector(query_text, ordered)
    if isinstance(raw, EvidenceSpanSelectionPayload):
        candidates = [item.model_dump(mode="json") for item in raw.spans]
    elif isinstance(raw, dict) and set(raw) <= {"spans"} and isinstance(raw.get("spans", []), list):
        candidates = raw.get("spans", [])
    else:
        raise ValueError("Selector output must contain only a spans list")

    selected = []
    diagnostics = []
    seen = set()
    for candidate_index, candidate in enumerate(candidates):
        try:
            span = EvidenceSpanSelection.model_validate(candidate)
            if span.start_turn_index > span.end_turn_index:
                raise ValueError("start_turn_index must be less than or equal to end_turn_index")
            missing = [index for index in range(span.start_turn_index, span.end_turn_index + 1) if index not in by_index]
            if missing:
                raise ValueError(f"Selected span is outside the candidate region or has missing turns: {missing}")
        except (ValidationError, ValueError) as error:
            diagnostics.append(EvidenceExtractionDiagnostic(
                candidate_index=candidate_index, code="invalid_selected_span", message=str(error),
            ))
            continue
        key = (span.start_turn_index, span.end_turn_index)
        if key in seen:
            diagnostics.append(EvidenceExtractionDiagnostic(
                candidate_index=candidate_index, code="duplicate_selected_span", message=f"Duplicate span ignored: {key}",
            ))
            continue
        seen.add(key)
        selected.append(SelectedEvidenceSpan(
            session_id=scope[2], session_number=session_number,
            start_turn_index=span.start_turn_index, end_turn_index=span.end_turn_index,
            source_ref=build_transcript_source_ref(scope[2], span.start_turn_index, span.end_turn_index),
            evidence_text=build_transcript_span_text(ordered, span.start_turn_index, span.end_turn_index),
            retrieval_score=retrieval_score, retrieval_rank=retrieval_rank,
        ))
    return selected, diagnostics


def _invoke_query_span_selector(
    query_text: str, region_turns: list[StoredTranscriptTurn],
) -> EvidenceSpanSelectionPayload:
    if settings.stub_mode:
        raise RuntimeError("Query-conditioned evidence selection requires an LLM or explicit test selector.")
    return _query_span_selector_llm().invoke(_build_query_span_prompt(query_text, region_turns))


def _query_span_selector_llm():
    llm = get_llm().model_copy(update={"temperature": 0.0})
    return llm.with_structured_output(EvidenceSpanSelectionPayload, method="function_calling")


def _build_query_span_prompt(query_text: str, region_turns: list[StoredTranscriptTurn]) -> str:
    transcript = "\n".join(
        f"{turn.turn_index} [{turn.speaker_role}] {turn.sanitized_text}" for turn in region_turns
    )
    return f"""Select the minimal self-contained raw source span(s) that directly support the query.
Return structured data only. Each span may contain ONLY start_turn_index and end_turn_index.
Never return text, summary, reason, interpretation, clinical meaning, episode type, intervention labels,
client-response labels, progress, diagnosis, or confidence text. Return {{"spans": []}} when this region
does not actually support the query. Do not force evidence.

Include enough source context to understand the evidence:
- For a counselor practice/intervention query, include the actual counselor action and the client's relevant response.
- For an outside event/attempt query, include the event, client action, other person's response, and outcome when present.
- Keep the span minimal; exclude unrelated setup or later planning.
- Use only continuous existing indices inside this candidate region.

Query:
{query_text}

Candidate region:
{transcript}
"""
