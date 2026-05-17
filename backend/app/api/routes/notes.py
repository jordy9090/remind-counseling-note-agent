"""Routes for note generation."""
from __future__ import annotations

import traceback

from fastapi import APIRouter, HTTPException

from app.graph.graph import run_note_pipeline
from app.schemas.note import GenerateNoteResponse, SessionInput

router = APIRouter(prefix="/api/notes", tags=["notes"])


@router.post("/generate", response_model=GenerateNoteResponse)
async def generate_note(session_input: SessionInput) -> GenerateNoteResponse:
    """Run the MVP V0 six-agent note generation workflow."""
    try:
        return run_note_pipeline(session_input)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"회기요약 생성 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/session-draft", response_model=GenerateNoteResponse, include_in_schema=False)
async def create_session_draft_compat(session_input: SessionInput) -> GenerateNoteResponse:
    """Backward-compatible alias for older local clients."""
    return await generate_note(session_input)
