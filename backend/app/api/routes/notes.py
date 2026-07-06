"""Routes for note generation."""
from __future__ import annotations

import traceback

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.graph.graph import run_note_pipeline
from app.graph.supervision_report import run_supervision_report_pipeline
from app.schemas.note import (
    GenerateNoteResponse,
    RecomposeNoteRequest,
    RecomposeNoteResponse,
    SessionInput,
    SupervisionReportDraft,
    SupervisionReportRequest,
    TemporaryDraftRecord,
    TemporaryDraftSaveRequest,
    TemporaryDraftSaveResponse,
)
from app.services.draft_store import get_temporary_draft, list_temporary_drafts, save_temporary_draft
from app.services.recompose_cache import recompose_note_with_cache
from app.services.supabase_storage import persist_generated_note

router = APIRouter(prefix="/api/notes", tags=["notes"])


@router.post("/generate", response_model=GenerateNoteResponse)
async def generate_note(session_input: SessionInput) -> GenerateNoteResponse:
    """Run the full six-agent workflow and return Pydantic-validated JSON."""
    return _run_pipeline_with_stub_fallback(session_input)


@router.post("/recompose", response_model=RecomposeNoteResponse)
async def recompose_note_draft(request: RecomposeNoteRequest) -> RecomposeNoteResponse:
    """Regenerate a note draft for the selected checklist configuration."""
    try:
        return recompose_note_with_cache(request)
    except Exception as error:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"요약초안 재구성 중 오류가 발생했습니다: {str(error)}",
        )


@router.post("/supervision-report", response_model=SupervisionReportDraft)
async def generate_supervision_report(request: SupervisionReportRequest) -> SupervisionReportDraft:
    """Generate a Korean personal counseling case supervision report draft."""
    try:
        return run_supervision_report_pipeline(request)
    except Exception as error:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"수퍼비전 보고서 초안 생성 중 오류가 발생했습니다: {str(error)}",
        )


@router.post("/drafts", response_model=TemporaryDraftSaveResponse)
async def save_note_draft(draft: TemporaryDraftSaveRequest) -> TemporaryDraftSaveResponse:
    """Persist a counselor's temporary workspace draft."""
    return save_temporary_draft(draft)


@router.get("/drafts/{draft_id}", response_model=TemporaryDraftRecord)
async def get_note_draft(draft_id: str) -> TemporaryDraftRecord:
    """Return a saved temporary draft."""
    draft = get_temporary_draft(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="임시저장 초안을 찾을 수 없습니다.")
    return draft


@router.get("/drafts", response_model=list[TemporaryDraftRecord])
async def list_note_drafts(case_id: str | None = None) -> list[TemporaryDraftRecord]:
    """Return temporary drafts, optionally filtered by case id."""
    return list_temporary_drafts(case_id=case_id)


def _run_pipeline_with_stub_fallback(session_input: SessionInput) -> GenerateNoteResponse:
    try:
        result = run_note_pipeline(session_input)
        result.persistence_report = persist_generated_note(session_input, result)
        return result
    except Exception as error:
        traceback.print_exc()
        original_use_stub = settings.use_stub
        try:
            settings.use_stub = True
            result = run_note_pipeline(session_input)
            result.persistence_report = persist_generated_note(session_input, result)
            return result
        except Exception:
            traceback.print_exc()
            raise HTTPException(
                status_code=500,
                detail=f"회기요약 생성 중 오류가 발생했습니다: {str(error)}",
            )
        finally:
            settings.use_stub = original_use_stub
