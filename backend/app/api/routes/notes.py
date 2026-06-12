"""Routes for note generation."""
from __future__ import annotations

import traceback

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.graph.graph import run_note_pipeline
from app.schemas.note import EvidenceCheckItem, GenerateNoteResponse, NoteDraftResponse, SessionInput

router = APIRouter(prefix="/api/notes", tags=["notes"])


@router.post("/generate", response_model=GenerateNoteResponse)
async def generate_note(session_input: SessionInput) -> GenerateNoteResponse:
    """Run the full six-agent workflow and return Pydantic-validated JSON."""
    return _run_pipeline_with_stub_fallback(session_input)


@router.post("/generate-compact", response_model=NoteDraftResponse, include_in_schema=False)
async def generate_note_compact(session_input: SessionInput) -> NoteDraftResponse:
    """Legacy compact response for older local demos."""
    full_response = _run_pipeline_with_stub_fallback(session_input)
    return _to_note_draft_response(full_response)


@router.post("/session-draft", response_model=GenerateNoteResponse, include_in_schema=False)
async def create_session_draft_compat(session_input: SessionInput) -> GenerateNoteResponse:
    """Backward-compatible full response for older local clients."""
    return _run_pipeline_with_stub_fallback(session_input)


def _run_pipeline_with_stub_fallback(session_input: SessionInput) -> GenerateNoteResponse:
    try:
        return run_note_pipeline(session_input)
    except Exception as error:
        traceback.print_exc()
        original_use_stub = settings.use_stub
        try:
            settings.use_stub = True
            return run_note_pipeline(session_input)
        except Exception:
            traceback.print_exc()
            raise HTTPException(
                status_code=500,
                detail=f"회기요약 생성 중 오류가 발생했습니다: {str(error)}",
            )
        finally:
            settings.use_stub = original_use_stub


def _to_note_draft_response(full_response: GenerateNoteResponse) -> NoteDraftResponse:
    draft = full_response.session_summary_draft
    verification = full_response.verification_report

    warnings = [
        "AI 초안은 상담사의 검토 전 최종 회기 기록으로 사용되지 않습니다.",
        *[item.claim for item in verification.unsupported_or_risky_claims],
        *[f"민감정보 후보: {item.text}" for item in verification.sensitive_info_items],
    ]
    missing_items = [
        *full_response.document_transform_preview.missing_required_fields,
        *[item.field for item in verification.requires_counselor_review],
    ]

    return NoteDraftResponse(
        case_id=draft.session_info.case_id,
        session_number=draft.session_info.session_number,
        session_summary=draft.session_content.text,
        main_issue=draft.presenting_problem.text,
        counselor_intervention=draft.counselor_intervention.text,
        client_response=draft.client_response.text,
        next_plan=draft.next_plan.text,
        evidence_check=_build_evidence_check(full_response),
        missing_items=_unique(missing_items),
        warnings=_unique(warnings),
    )


def _build_evidence_check(full_response: GenerateNoteResponse) -> list[EvidenceCheckItem]:
    items: list[EvidenceCheckItem] = []
    for mapped in full_response.evidence_mapped_data.items:
        if mapped.field in {"reflection_candidates"}:
            continue
        source_type = _source_type(mapped.evidence_type, mapped.source_refs)
        items.append(
            EvidenceCheckItem(
                claim=mapped.content,
                source_type=source_type,
                source_excerpt=_source_excerpt(full_response, source_type, mapped.source_refs),
                confidence=_confidence(mapped.evidence_type),
            )
        )
    return items[:8]


def _source_type(evidence_type: str, refs: list[str]) -> str:
    if evidence_type in {"inferred", "model_inference", "needs_review"}:
        return "ai_inference"
    if "transcript_text" in refs:
        return "transcript"
    if "counselor_memo" in refs or "nonverbal_notes" in refs:
        return "counselor_memo"
    if "previous_session_summary" in refs:
        return "previous_summary"
    return "ai_inference"


def _source_excerpt(full_response: GenerateNoteResponse, source_type: str, refs: list[str]) -> str:
    sources = full_response.sanitized_input.sources
    if "nonverbal_notes" in refs:
        source_text = sources.nonverbal_notes
    elif source_type == "transcript":
        source_text = sources.transcript_text
    elif source_type == "counselor_memo":
        source_text = sources.counselor_memo
    elif source_type == "previous_summary":
        source_text = sources.previous_session_summary
    else:
        source_text = "입력 자료를 바탕으로 한 AI 요약/추론입니다. 상담사 확인이 필요합니다."
    compact = " ".join(source_text.split())
    return compact[:180] + ("..." if len(compact) > 180 else "")


def _confidence(evidence_type: str) -> str:
    if evidence_type == "direct":
        return "high"
    if evidence_type in {"mixed", "counselor_input", "previous_context"}:
        return "medium"
    return "low"


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
