"""Routes for per-case dashboard and scheduling metadata."""
from __future__ import annotations

import traceback
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.security import require_preview_access
from app.core.config import settings
from app.schemas.note import CaseDashboardResponse, CaseScheduleUpdateRequest
from app.services.supabase_storage import (
    SupabaseStorageError,
    fetch_case_dashboard,
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
    if "credentials are missing" in message:
        return 503
    return 502


@router.get("/{case_id}/dashboard", response_model=CaseDashboardResponse)
async def get_case_dashboard(case_id: str, actor: PreviewActor) -> CaseDashboardResponse:
    """사례별 총 회기 수, 최초/최근 상담일, 회기 요약, 생성 문서 목록을 반환한다."""
    if not settings.supabase_configured:
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
    if not settings.supabase_configured:
        raise HTTPException(status_code=503, detail="Supabase가 설정되지 않아 일정 수정을 사용할 수 없습니다.")
    try:
        return update_case_schedule(case_id, request, actor=actor)
    except SupabaseStorageError as error:
        raise HTTPException(status_code=_storage_error_status(error), detail=str(error))
    except Exception as error:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"사례 일정 수정 중 오류가 발생했습니다: {str(error)}")
