"""Shared normalization, structuring, summarization, and evidence-review core."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.graph.nodes import (
    generate_summary,
    map_evidence,
    sanitize_input,
    structure_session,
    verify_evidence_deterministically,
)
from app.schemas.note import EvidenceItem, SanitizedInput, SessionInput, StructuredCaseData
from app.services.transcript_chunking import (
    SourceChunk,
    TranscriptLimitError,
    estimate_korean_tokens,
    split_source_text,
)


class SummaryExecutionMode(str, Enum):
    PUBLIC_QUICK = "public_quick"
    AUTHENTICATED_FULL = "authenticated_full"


@dataclass(frozen=True)
class SummaryCorePolicy:
    mode: SummaryExecutionMode
    allow_retrieval_context: bool
    allow_persistence: bool
    deterministic_verification: bool
    max_input_chars: int
    max_estimated_input_tokens: int
    chunk_threshold_chars: int
    chunk_target_chars: int
    max_chunks: int
    max_core_provider_calls: int


PUBLIC_QUICK_POLICY = SummaryCorePolicy(
    mode=SummaryExecutionMode.PUBLIC_QUICK,
    allow_retrieval_context=False,
    allow_persistence=False,
    deterministic_verification=True,
    max_input_chars=20_000,
    max_estimated_input_tokens=20_000,
    chunk_threshold_chars=20_000,
    chunk_target_chars=20_000,
    max_chunks=1,
    max_core_provider_calls=3,
)

AUTHENTICATED_FULL_POLICY = SummaryCorePolicy(
    mode=SummaryExecutionMode.AUTHENTICATED_FULL,
    allow_retrieval_context=True,
    allow_persistence=True,
    deterministic_verification=True,
    max_input_chars=96_000,
    max_estimated_input_tokens=96_000,
    chunk_threshold_chars=12_000,
    chunk_target_chars=14_000,
    max_chunks=8,
    max_core_provider_calls=10,
)

_RETRIEVAL_STATE_KEYS = {
    "retrieved_case_context",
    "retrieved_case_memory_chunks",
    "retrieved_authoritative_kb_chunks",
    "retrieved_template_context",
    "retrieved_privacy_context",
    "raw_regions_by_need",
    "grounding_context",
    "grounding",
}


def run_summary_core(
    state: dict[str, Any],
    *,
    policy: SummaryCorePolicy,
) -> dict[str, Any]:
    """Run the shared AI core without retrieval, persistence, or document transforms.

    The caller selects an immutable request policy. Public requests fail closed if
    authenticated context or persistence accidentally enters their state.
    """
    session_input: SessionInput = state["session_input"]
    _validate_policy_boundary(state, session_input, policy)
    if not state.get("input_budget_prevalidated"):
        validate_summary_input_budget(session_input, policy=policy)

    working_state = dict(state)
    updates: dict[str, Any] = {}
    if "sanitized_input" not in working_state:
        _apply_step(working_state, updates, sanitize_input)
    sanitized: SanitizedInput = working_state["sanitized_input"]
    input_chars = _current_input_chars(sanitized)
    if input_chars > policy.max_input_chars:
        raise TranscriptLimitError(
            f"요청당 입력 한도는 {policy.max_input_chars:,}자입니다. 현재 {input_chars:,}자입니다."
        )
    estimated_input_tokens = estimate_korean_tokens(_current_input_text(sanitized))
    if estimated_input_tokens > policy.max_estimated_input_tokens:
        raise TranscriptLimitError(
            f"요청당 추정 입력 토큰 한도는 {policy.max_estimated_input_tokens:,}개입니다."
        )
    if input_chars > policy.chunk_threshold_chars:
        chunk_updates = _structure_long_input(working_state, sanitized, policy)
        working_state.update(chunk_updates)
        updates.update(chunk_updates)
    else:
        if 3 > policy.max_core_provider_calls:
            raise TranscriptLimitError("요청당 AI 호출 상한이 요약 처리에 필요한 호출 수보다 작습니다.")
        _apply_step(working_state, updates, structure_session)
        if policy.mode == SummaryExecutionMode.PUBLIC_QUICK:
            working_state["compact_summary_context"] = True
            updates["compact_summary_context"] = True
    _apply_step(working_state, updates, map_evidence)
    _apply_step(working_state, updates, generate_summary)
    if policy.deterministic_verification:
        verification_updates = verify_evidence_deterministically(working_state)
        working_state.update(verification_updates)
        updates["session_summary_draft"] = verification_updates["session_summary_draft"]
        if policy.mode == SummaryExecutionMode.PUBLIC_QUICK:
            updates["verification_report"] = verification_updates["verification_report"]
        else:
            updates["core_verification_report"] = verification_updates["verification_report"]
    return updates


def validate_summary_input_budget(
    session_input: SessionInput,
    *,
    policy: SummaryCorePolicy,
) -> None:
    """Reject oversized raw requests before storage de-identification or provider use."""
    input_text = "".join(
        (
            session_input.counselor_memo,
            session_input.transcript_text,
            session_input.previous_session_summary,
            session_input.counseling_goal,
            "".join(session_input.key_issue_tags),
            session_input.psychological_test_summary,
            session_input.nonverbal_notes,
        )
    )
    if len(input_text) > policy.max_input_chars:
        raise TranscriptLimitError(
            f"요청당 입력 한도는 {policy.max_input_chars:,}자입니다. 현재 {len(input_text):,}자입니다."
        )
    if estimate_korean_tokens(input_text) > policy.max_estimated_input_tokens:
        raise TranscriptLimitError(
            f"요청당 추정 입력 토큰 한도는 {policy.max_estimated_input_tokens:,}개입니다."
        )


def summary_core_node(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph node for the authenticated Full Session Summary workflow."""
    return run_summary_core(state, policy=AUTHENTICATED_FULL_POLICY)


def _apply_step(
    working_state: dict[str, Any],
    updates: dict[str, Any],
    step,
) -> None:
    step_updates = step(working_state)
    working_state.update(step_updates)
    updates.update(step_updates)


def _validate_policy_boundary(
    state: dict[str, Any],
    session_input: SessionInput,
    policy: SummaryCorePolicy,
) -> None:
    if session_input.persist and not policy.allow_persistence:
        raise ValueError("Public summary execution cannot persist counseling data.")
    if policy.allow_retrieval_context:
        return
    populated_context = [key for key in _RETRIEVAL_STATE_KEYS if state.get(key)]
    if populated_context:
        raise ValueError("Public summary execution cannot use authenticated retrieval context.")
    if state.get("actor"):
        raise ValueError("Public summary execution cannot use an authenticated actor.")
    if session_input.previous_session_summary.strip():
        raise ValueError("Public summary execution cannot load previous-session context.")


def _current_input_chars(sanitized: SanitizedInput) -> int:
    return len(_current_input_text(sanitized))


def _current_input_text(sanitized: SanitizedInput) -> str:
    return "".join(
        (
            sanitized.sources.counselor_memo,
            sanitized.sources.transcript_text,
            sanitized.sources.previous_session_summary,
            sanitized.sources.counseling_goal,
            "".join(sanitized.sources.key_issue_tags),
            sanitized.sources.psychological_test_summary,
            sanitized.sources.nonverbal_notes,
        )
    )


def _structure_long_input(
    state: dict[str, Any],
    sanitized: SanitizedInput,
    policy: SummaryCorePolicy,
) -> dict[str, Any]:
    chunks = _source_chunks(sanitized, policy)
    expected_calls = len(chunks) + 2
    if expected_calls > policy.max_core_provider_calls:
        raise TranscriptLimitError(
            f"예상 AI 호출 {expected_calls}회가 요청당 상한 {policy.max_core_provider_calls}회를 초과합니다."
        )

    structured_parts: list[StructuredCaseData] = []
    source_segments: dict[str, str] = {}
    for chunk in chunks:
        source_segments[chunk.source_ref] = chunk.text
        chunk_state = dict(state)
        chunk_state["sanitized_input"] = _sanitized_chunk(sanitized, chunk)
        try:
            structured = structure_session(chunk_state)["structured_case_data"]
        except Exception as error:
            raise RuntimeError(
                f"긴 상담자료의 {chunk.index}/{chunk.total} 청크 처리에 실패했습니다. 전체 요약을 생성하지 않았습니다."
            ) from error
        _replace_chunk_source_refs(structured, chunk)
        structured_parts.append(structured)

    return {
        "structured_case_data": _merge_structured_parts(structured_parts),
        "source_segments": source_segments,
        "hierarchical_summary": True,
    }


def _source_chunks(sanitized: SanitizedInput, policy: SummaryCorePolicy) -> list[SourceChunk]:
    chunks: list[SourceChunk] = []
    remaining = policy.max_chunks
    for source_field, text in (
        ("counselor_memo", sanitized.sources.counselor_memo),
        ("transcript_text", sanitized.sources.transcript_text),
    ):
        if not text:
            continue
        source_chunks = split_source_text(
            text,
            source_field=source_field,
            target_chars=policy.chunk_target_chars,
            max_chunks=remaining,
        )
        chunks.extend(source_chunks)
        remaining -= len(source_chunks)
    if not chunks:
        raise TranscriptLimitError("청크로 처리할 현재 회기 메모나 축어록이 없습니다.")
    total = len(chunks)
    return [
        SourceChunk(
            source_field=chunk.source_field,
            source_ref=chunk.source_ref,
            text=chunk.text,
            start_char=chunk.start_char,
            end_char=chunk.end_char,
            index=index,
            total=total,
        )
        for index, chunk in enumerate(chunks, 1)
    ]


def _sanitized_chunk(sanitized: SanitizedInput, chunk: SourceChunk) -> SanitizedInput:
    updates: dict[str, Any] = {
        "counselor_memo": chunk.text if chunk.source_field == "counselor_memo" else "",
        "transcript_text": chunk.text if chunk.source_field == "transcript_text" else "",
    }
    if chunk.index != 1:
        updates.update(
            previous_session_summary="",
            counseling_goal="",
            psychological_test_summary="",
            key_issue_tags=[],
            nonverbal_notes="",
        )
    sources = sanitized.sources.model_copy(update=updates, deep=True)
    return sanitized.model_copy(update={"sources": sources})


def _replace_chunk_source_refs(structured: StructuredCaseData, chunk: SourceChunk) -> None:
    for field_name in StructuredCaseData.model_fields:
        for item in getattr(structured, field_name):
            refs: list[str] = []
            for ref in item.source_refs:
                if ref == chunk.source_field:
                    refs.append(chunk.source_ref)
                elif ref not in {"counselor_memo", "transcript_text"}:
                    refs.append(ref)
            item.source_refs = list(dict.fromkeys(refs))
            if item.evidence_type == "direct" and not item.source_refs:
                item.evidence_type = "needs_review"


def _merge_structured_parts(parts: list[StructuredCaseData]) -> StructuredCaseData:
    merged: dict[str, list[EvidenceItem]] = {}
    for field_name in StructuredCaseData.model_fields:
        items: list[EvidenceItem] = []
        by_content: dict[str, EvidenceItem] = {}
        for part in parts:
            for item in getattr(part, field_name):
                key = "".join(item.content.split()).casefold()
                if key in by_content:
                    existing = by_content[key]
                    existing.source_refs = list(dict.fromkeys([*existing.source_refs, *item.source_refs]))
                    continue
                copied = item.model_copy(deep=True)
                by_content[key] = copied
                items.append(copied)
        merged[field_name] = items
    return StructuredCaseData(**merged)
