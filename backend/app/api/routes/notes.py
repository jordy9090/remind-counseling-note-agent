"""Routes for note generation."""
from __future__ import annotations

import ipaddress
import os
import traceback
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response

from app.api.security import _require_supabase_user, require_preview_access
from app.graph.graph import run_note_pipeline
from app.graph.summary_core import AUTHENTICATED_FULL_POLICY, validate_summary_input_budget
from app.graph.supervision_report import run_supervision_report_pipeline
from app.schemas.note import (
    ConfirmGeneratedNoteRequest,
    ConfirmGeneratedNoteResponse,
    GenerateNoteResponse,
    GeneratedNoteRecord,
    RecomposeNoteRequest,
    RecomposeNoteResponse,
    SessionInput,
    SessionInputDeletionResponse,
    SupervisionReportDraft,
    SupervisionReportRequest,
    TemporaryDraftRecord,
    TemporaryDraftSaveRequest,
    TemporaryDraftSaveResponse,
)
from app.core.config import settings
from app.services.quick_summary import (
    QuickSummaryBusy,
    QuickSummaryCostLimit,
    QuickSummaryInputError,
    QuickSummaryRateLimited,
    QuickSummaryRequest,
    QuickSummaryResponse,
    generate_quick_summary,
    credential_rate_limit_key,
    rate_limit_key,
    rate_limiter,
)
from app.services.llm import observe_llm_request
from app.services.storage_deidentification import deidentify_session_input
from app.services.draft_store import (
    TemporaryDraftLimitError,
    get_temporary_draft,
    list_temporary_drafts,
    save_temporary_draft,
)
from app.services.recompose_cache import recompose_note_with_cache
from app.services.summary_quality import SummaryQualityError
from app.services.transcript_chunking import TranscriptLimitError
from app.schemas.storage_policy import NoteStoragePolicy
from app.services.storage_policy import note_storage_policy
from app.services.supabase_storage import (
    NoteConfirmationError,
    confirm_generated_note,
    delete_session_input,
    fetch_generated_note,
    persist_generated_note,
    persist_supervision_report,
)

router = APIRouter(prefix="/api/notes", tags=["notes"])
PreviewActor = Annotated[str, Depends(require_preview_access)]


@router.get("/storage-policy", response_model=NoteStoragePolicy)
async def get_note_storage_policy(actor: PreviewActor, response: Response) -> NoteStoragePolicy:
    """Describe this runtime's new-save behavior without reading existing records."""
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization"
    return note_storage_policy(actor)


@router.post("/generate", response_model=GenerateNoteResponse)
async def generate_note(session_input: SessionInput, actor: PreviewActor) -> GenerateNoteResponse:
    """Run the note-generation workflow and return Pydantic-validated JSON."""
    return _run_pipeline_with_stub_fallback(session_input, actor=actor)


@router.post("/quick-summary", response_model=QuickSummaryResponse)
async def quick_summary(
    payload: QuickSummaryRequest,
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> QuickSummaryResponse:
    return run_quick_summary(payload, request=request, authorization=authorization)


@router.post("/confirm", response_model=ConfirmGeneratedNoteResponse)
async def confirm_note(request: ConfirmGeneratedNoteRequest, actor: PreviewActor) -> ConfirmGeneratedNoteResponse:
    """Mark a generated note as counselor-confirmed and create case memory chunks."""
    try:
        return confirm_generated_note(request, actor=actor)
    except NoteConfirmationError as error:
        raise HTTPException(status_code=error.status_code, detail=error.message)
    except HTTPException:
        raise
    except Exception as error:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Note confirmation failed: {str(error)}")


@router.get("/records/{note_id}", response_model=GeneratedNoteRecord)
async def get_note_record(note_id: str, actor: PreviewActor, response: Response) -> GeneratedNoteRecord:
    """Return the complete owned draft and confirmed record without regenerating."""
    try:
        response.headers["Cache-Control"] = "private, no-store"
        return fetch_generated_note(note_id, actor=actor)
    except NoteConfirmationError as error:
        raise HTTPException(status_code=error.status_code, detail=error.message)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="저장된 기록을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.")


@router.post("/records/{note_id}/input-deletion", response_model=SessionInputDeletionResponse)
async def delete_note_session_input(note_id: str, actor: PreviewActor, response: Response) -> SessionInputDeletionResponse:
    """회기별 원문 삭제: remove the stored input of the note's session; the summary is kept."""
    try:
        response.headers["Cache-Control"] = "private, no-store"
        return delete_session_input(note_id, actor=actor)
    except NoteConfirmationError as error:
        raise HTTPException(status_code=error.status_code, detail=error.message)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="원문을 삭제하지 못했습니다. 잠시 후 다시 시도해주세요.")


@router.post("/recompose", response_model=RecomposeNoteResponse)
async def recompose_note_draft(request: RecomposeNoteRequest, actor: PreviewActor) -> RecomposeNoteResponse:
    """Regenerate a note draft for the selected checklist configuration."""
    try:
        with observe_llm_request("recompose_summary", max_calls=16):
            return recompose_note_with_cache(request, actor=actor)
    except TranscriptLimitError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except SummaryQualityError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="요약초안 재구성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
        ) from None


@router.post("/supervision-report", response_model=SupervisionReportDraft)
async def generate_supervision_report(request: SupervisionReportRequest, actor: PreviewActor) -> SupervisionReportDraft:
    """Generate a Korean personal counseling case supervision report draft."""
    try:
        with observe_llm_request("supervision_report", max_calls=4):
            if request.persist and settings.enable_persistence:
                request = request.model_copy(update={"session_input": deidentify_session_input(request.session_input)[0]})
            report = run_supervision_report_pipeline(request)
            # persist=true면 생성 성공 후에만 문서 레코드를 만든다 (실패 시 pending 레코드가 남지 않음)
            report.persistence = persist_supervision_report(request, report, actor=actor)
            return report
    except Exception as error:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"수퍼비전 보고서 초안 생성 중 오류가 발생했습니다: {str(error)}",
        )


@router.post("/drafts", response_model=TemporaryDraftSaveResponse)
async def save_note_draft(draft: TemporaryDraftSaveRequest, actor: PreviewActor) -> TemporaryDraftSaveResponse:
    """Persist a counselor's temporary workspace draft."""
    try:
        return save_temporary_draft(draft, actor=actor)
    except TemporaryDraftLimitError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error


@router.get("/drafts/{draft_id}", response_model=TemporaryDraftRecord)
async def get_note_draft(draft_id: str, actor: PreviewActor) -> TemporaryDraftRecord:
    """Return a saved temporary draft."""
    draft = get_temporary_draft(draft_id, actor=actor)
    if draft is None:
        raise HTTPException(status_code=404, detail="임시저장 초안을 찾을 수 없습니다.")
    return draft


@router.get("/drafts", response_model=list[TemporaryDraftRecord])
async def list_note_drafts(
    actor: PreviewActor,
    case_id: Annotated[str | None, Query(max_length=80)] = None,
) -> list[TemporaryDraftRecord]:
    """Return temporary drafts, optionally filtered by case id."""
    return list_temporary_drafts(actor=actor, case_id=case_id)


def _run_pipeline_with_stub_fallback(session_input: SessionInput, *, actor: str) -> GenerateNoteResponse:
    """Generate once and persist only success; retain the helper name for wrappers.

    Explicit demo mode still runs the configured stub. A failed real generation
    must never switch shared settings or replace a user's record with demo text.
    """
    with observe_llm_request("full_summary", max_calls=16):
        original_session_input = session_input
        try:
            validate_summary_input_budget(session_input, policy=AUTHENTICATED_FULL_POLICY)
            if session_input.persist and settings.enable_persistence:
                # Everything stored for this session derives from the de-identified input:
                # names masked (홍O동), occupations generalized (교육자).
                session_input, _ = deidentify_session_input(session_input)
            result = run_note_pipeline(
                session_input,
                actor=actor,
                input_budget_prevalidated=True,
            )
        except TranscriptLimitError as error:
            raise HTTPException(status_code=413, detail=str(error)) from error
        except SummaryQualityError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(
                status_code=502,
                detail="회기요약을 생성하지 못했습니다. 입력 내용을 유지한 채 잠시 후 다시 시도해 주세요.",
            ) from error
        result.persistence_report = persist_generated_note(
            session_input,
            result,
            actor=actor,
            original_session_input=original_session_input,
        )
        return result


def client_ip(request: Request) -> str:
    """Return a canonical IP, trusting forwarded headers only behind a configured proxy."""
    candidates: list[str] = []
    if os.getenv("VERCEL") == "1" or settings.trust_proxy_client_ip_headers:
        candidates.extend([
            (request.headers.get("x-vercel-forwarded-for") or "").split(",")[0].strip(),
            (request.headers.get("x-forwarded-for") or "").split(",")[0].strip(),
            (request.headers.get("x-real-ip") or "").strip(),
        ])
    candidates.append(request.client.host if request.client else "")
    for candidate in candidates:
        try:
            return ipaddress.ip_address(candidate).compressed
        except ValueError:
            continue
    return ""


def _optional_actor(authorization: str | None) -> str | None:
    """Signed-in callers get a per-user quota; an invalid token falls back to the IP quota."""
    if not authorization or not settings.enable_real_user_auth:
        return None
    try:
        return str(_require_supabase_user(authorization))
    except HTTPException:
        return None


def run_quick_summary(
    payload: QuickSummaryRequest,
    *,
    request: Request,
    authorization: str | None,
) -> QuickSummaryResponse:
    """Public quick summary. The input text is never stored or logged."""
    ip_key, anonymous_limit, anonymous_window = rate_limit_key(
        client_ip=client_ip(request), actor=None
    )
    try:
        rate_limiter.check(ip_key, anonymous_limit, anonymous_window)
        if authorization and settings.enable_real_user_auth:
            credential_key, credential_limit, credential_window = credential_rate_limit_key(authorization)
            rate_limiter.check(credential_key, credential_limit, credential_window)
    except QuickSummaryRateLimited as error:
        raise HTTPException(
            status_code=429,
            detail="요약 요청이 너무 많아요. 잠시 후 다시 시도하거나 로그인 후 이용해주세요.",
            headers={"Retry-After": str(error.retry_after)},
        ) from error

    actor = _optional_actor(authorization)
    if actor:
        rate_limiter.refund(ip_key)
        actor_key, actor_limit, actor_window = rate_limit_key(client_ip="", actor=actor)
        try:
            rate_limiter.check(actor_key, actor_limit, actor_window)
        except QuickSummaryRateLimited as error:
            raise HTTPException(
                status_code=429,
                detail="요약 요청이 너무 많아요. 잠시 후 다시 시도해주세요.",
                headers={"Retry-After": str(error.retry_after)},
            ) from error
    try:
        with observe_llm_request("public_quick_summary", max_calls=3):
            return generate_quick_summary(payload.text)
    except QuickSummaryInputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except QuickSummaryBusy as error:
        raise HTTPException(
            status_code=503,
            detail="현재 요약 요청이 많아요. 잠시 후 다시 시도해주세요.",
            headers={"Retry-After": "1"},
        ) from error
    except QuickSummaryCostLimit as error:
        raise HTTPException(
            status_code=503,
            detail="현재 설정된 요청 비용 한도를 초과해 요약을 실행할 수 없어요.",
        ) from error
    except Exception:
        # Do not attach the input text or provider payload to the error.
        raise HTTPException(
            status_code=502,
            detail="요약을 만들지 못했어요. 잠시 후 다시 시도해주세요.",
        ) from None
