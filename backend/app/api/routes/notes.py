"""상담 회기 정보 처리 엔드포인트"""
from fastapi import APIRouter, HTTPException
from app.schemas.session import SessionInput
from app.schemas.structured_case import StructuredCase
from app.schemas.summary import SessionSummary
from app.schemas.verification import VerificationReport
from app.graph.workflow import app
from app.graph.state import GraphState
from pydantic import BaseModel

router = APIRouter(prefix="/api/notes", tags=["notes"])


class SessionDraftResponse(BaseModel):
    """세션 드래프트 응답"""
    structured: StructuredCase
    summary: SessionSummary
    verification: VerificationReport


@router.post("/session-draft", response_model=SessionDraftResponse)
async def create_session_draft(session_input: SessionInput):
    """
    상담 회기 정보를 입력받아 구조화, 요약, 검증 수행
    
    - POST /api/notes/session-draft
    - Input: {case_id, session_no, counselor_memo, transcript, prev_summary?}
    - Output: {structured, summary, verification}
    """
    try:
        # 초기 상태 생성
        initial_state: GraphState = {
            "input": session_input,
            "structured": None,
            "summary": None,
            "verification": None,
        }
        
        # 워크플로우 실행
        result = app.invoke(initial_state)
        
        # 응답 생성
        return SessionDraftResponse(
            structured=result["structured"],
            summary=result["summary"],
            verification=result["verification"],
        )
    
    except Exception as e:
        # 오류 처리
        raise HTTPException(
            status_code=500,
            detail=f"회기 요약 생성 중 오류 발생: {str(e)}"
        )
