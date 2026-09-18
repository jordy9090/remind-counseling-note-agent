"""Routes for per-case dashboard and scheduling metadata."""
from __future__ import annotations

import traceback
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.security import require_preview_access
from app.core.config import settings
from app.schemas.note import (
    CaseCreateRequest,
    CaseDashboardResponse,
    CaseListResponse,
    CaseProfileUpdateRequest,
    CaseScheduleUpdateRequest,
)
from app.services.supabase_storage import (
    SupabaseStorageError,
    create_case,
    fetch_case_dashboard,
    list_cases,
    update_case_profile,
    update_case_schedule,
)

router = APIRouter(prefix="/api/cases", tags=["cases"])
PreviewActor = Annotated[str, Depends(require_preview_access)]


def _storage_error_status(error: SupabaseStorageError) -> int:
    message = str(error)
    if "찾을 수 없습니다" in message:
        return 404
    if "다른 사용자" in message:
        return 403
    if "이미 사용 중인" in message:
        return 409
    if "아직 준비되지 않았습니다" in message:
        return 503
    if "credentials are missing" in message:
        return 503
    return 502


def _require_storage(actor: str, feature: str) -> None:
    if not settings.supabase_configured and not getattr(actor, "access_token", ""):
        raise HTTPException(status_code=503, detail=f"Supabase가 설정되지 않아 {feature}을(를) 사용할 수 없습니다.")


@router.get("", response_model=CaseListResponse)
async def get_case_list(actor: PreviewActor) -> CaseListResponse:
    """로그인 사용자가 소유한 케이스 목록과 회기·문서·임시저장 집계를 반환한다."""
    if not settings.supabase_configured and not getattr(actor, "access_token", ""):
        raise HTTPException(status_code=503, detail="Supabase가 설정되지 않아 케이스 목록을 사용할 수 없습니다.")
    try:
        return list_cases(actor=actor)
    except SupabaseStorageError as error:
        raise HTTPException(status_code=_storage_error_status(error), detail=str(error))
    except Exception as error:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"케이스 목록 조회 중 오류가 발생했습니다: {str(error)}")


@router.post("", response_model=CaseDashboardResponse, status_code=201)
async def post_case(request: CaseCreateRequest, actor: PreviewActor) -> CaseDashboardResponse:
    """새 내담자(케이스)를 생성하고 대시보드 형태로 반환한다."""
    _require_storage(actor, "내담자 생성")
    try:
        return create_case(request, actor=actor)
    except SupabaseStorageError as error:
        raise HTTPException(status_code=_storage_error_status(error), detail=str(error))
    except Exception as error:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"내담자 생성 중 오류가 발생했습니다: {str(error)}")


@router.patch("/{case_id}/profile", response_model=CaseDashboardResponse)
async def patch_case_profile(
    case_id: str, request: CaseProfileUpdateRequest, actor: PreviewActor
) -> CaseDashboardResponse:
    """내담자 프로필·이름·상태를 수정하고 갱신된 대시보드를 반환한다."""
    _require_storage(actor, "프로필 수정")
    try:
        return update_case_profile(case_id, request, actor=actor)
    except SupabaseStorageError as error:
        raise HTTPException(status_code=_storage_error_status(error), detail=str(error))
    except Exception as error:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"프로필 수정 중 오류가 발생했습니다: {str(error)}")


@router.get("/{case_id}/dashboard", response_model=CaseDashboardResponse)
async def get_case_dashboard(case_id: str, actor: PreviewActor) -> CaseDashboardResponse:
    """사례별 총 회기 수, 최초/최근 상담일, 회기 요약, 생성 문서 목록을 반환한다."""
    if not settings.supabase_configured and not getattr(actor, "access_token", ""):
        raise HTTPException(status_code=503, detail="Supabase가 설정되지 않아 사례 대시보드를 사용할 수 없습니다.")
    try:
        return fetch_case_dashboard(case_id, actor=actor)
    except SupabaseStorageError as error:
        raise HTTPException(status_code=_storage_error_status(error), detail=str(error))
    except Exception as error:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"사례 대시보드 조회 중 오류가 발생했습니다: {str(error)}")


@router.patch("/{case_id}/schedule", response_model=CaseDashboardResponse)
async def patch_case_schedule(
    case_id: str, request: CaseScheduleUpdateRequest, actor: PreviewActor
) -> CaseDashboardResponse:
    """전체 예정 회기 수와 다음 상담 예정일을 수정하고 갱신된 대시보드를 반환한다."""
    if not settings.supabase_configured and not getattr(actor, "access_token", ""):
        raise HTTPException(status_code=503, detail="Supabase가 설정되지 않아 일정 수정을 사용할 수 없습니다.")
    try:
        return update_case_schedule(case_id, request, actor=actor)
    except SupabaseStorageError as error:
        raise HTTPException(status_code=_storage_error_status(error), detail=str(error))
    except Exception as error:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"사례 일정 수정 중 오류가 발생했습니다: {str(error)}")
