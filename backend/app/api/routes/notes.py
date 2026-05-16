"""상담 회기 정보 처리 엔드포인트"""
import traceback

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.pipeline import run_pipeline
from app.schemas.session import SessionInput
from app.schemas.structured_case import StructuredCase
from app.schemas.summary import SessionSummary
from app.schemas.verification import VerificationReport

router = APIRouter(prefix="/api/notes", tags=["notes"])


class SessionDraftResponse(BaseModel):
    """세션 드래프트 응답"""
    structured: StructuredCase
    summary: SessionSummary
    verification: VerificationReport
    stub: bool  # 스텁(샘플) 응답 여부


@router.post("/session-draft", response_model=SessionDraftResponse)
async def create_session_draft(session_input: SessionInput):
    """
    상담 회기 정보를 입력받아 구조화, 요약, 검증 수행

    - POST /api/notes/session-draft
    - Input: {case_id, session_no, counselor_memo, transcript, prev_summary?}
    - Output: {structured, summary, verification, stub}
    """
    try:
        result = run_pipeline(session_input)
        return SessionDraftResponse(
            structured=result.structured,
            summary=result.summary,
            verification=result.verification,
            stub=result.stub,
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"회기 요약 생성 중 오류 발생: {str(e)}",
        )
