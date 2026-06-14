"""Routes for note generation."""
from __future__ import annotations

import traceback

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.graph.graph import run_note_pipeline
from app.schemas.note import GenerateNoteResponse, SessionInput

router = APIRouter(prefix="/api/notes", tags=["notes"])


@router.post("/generate", response_model=GenerateNoteResponse)
async def generate_note(session_input: SessionInput) -> GenerateNoteResponse:
    """Run the full six-agent workflow and return Pydantic-validated JSON."""
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
