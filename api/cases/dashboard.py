"""Vercel serverless wrapper for every case endpoint (list, create, dashboard, schedule, profile).

A single function keeps the deployment under Vercel's 12-function limit. vercel.json rewrites:
  /api/cases                    → /api/cases/dashboard?scope=list           (GET list, POST create)
  /api/cases/:case_id/dashboard → /api/cases/dashboard?case_id=:case_id     (GET)
  /api/cases/:case_id/schedule  → /api/cases/dashboard?case_id=:case_id&scope=schedule (PATCH)
  /api/cases/:case_id/profile   → /api/cases/dashboard?case_id=:case_id&scope=profile  (PATCH)
"""
from __future__ import annotations

import sys
from pathlib import Path

from typing import Annotated, Any
from fastapi import Body, Depends, FastAPI, HTTPException, Response
from pydantic import ValidationError

ROOT_DIR = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "backend" / "app").exists()
)
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.security import require_preview_access  # noqa: E402
from app.api.routes.cases import (  # noqa: E402
    get_case_dashboard,
    get_case_list,
    patch_case_profile,
    patch_case_schedule,
    post_case,
    post_quick_summary_session,
)
from app.schemas.note import (  # noqa: E402
    CaseCreateRequest,
    CaseDashboardResponse,
    CaseListResponse,
    CaseProfileUpdateRequest,
    CaseScheduleUpdateRequest,
    QuickSummarySessionRequest,
    QuickSummarySessionResponse,
)

app = FastAPI(title="Re:mind Case API")
PreviewActor = Annotated[str, Depends(require_preview_access)]


def _validation_error(error: ValidationError) -> HTTPException:
    return HTTPException(status_code=422, detail=error.errors(include_url=False))


@app.get("/")
@app.get("/api/cases")
@app.get("/api/cases/dashboard")
async def list_or_dashboard(
    actor: PreviewActor,
    case_id: str | None = None,
    scope: str | None = None,
) -> CaseListResponse | CaseDashboardResponse:
    """case_id가 없거나 scope=list면 소유 케이스 목록, 있으면 해당 케이스 대시보드."""
    if case_id and scope != "list":
        return await get_case_dashboard(case_id, actor)
    return await get_case_list(actor)


@app.get("/api/cases/{case_id}/dashboard", response_model=CaseDashboardResponse)
async def dashboard(case_id: str, actor: PreviewActor) -> CaseDashboardResponse:
    return await get_case_dashboard(case_id, actor)


@app.post("/", status_code=201)
@app.post("/api/cases", status_code=201)
@app.post("/api/cases/dashboard", status_code=201)
async def create(
    actor: PreviewActor,
    case_id: str | None = None,
    scope: str | None = None,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> CaseDashboardResponse | QuickSummarySessionResponse:
    """scope=quick-summary면 간편 요약을 그 내담자의 다음 회기로 저장, 그 외는 새 내담자 생성."""
    try:
        if scope == "quick-summary":
            if not case_id:
                raise HTTPException(status_code=422, detail="A quick-summary save needs a case ID.")
            return await post_quick_summary_session(case_id, QuickSummarySessionRequest(**payload), actor)
        return await post_case(CaseCreateRequest(**payload), actor)
    except ValidationError as error:
        raise _validation_error(error)


# vercel.json rewrites /api/cases/:case_id/quick-summary to /api/cases/dashboard?case_id=...&scope=quick-summary.
@app.post("/api/cases/{case_id}/quick-summary", response_model=QuickSummarySessionResponse, status_code=201)
async def quick_summary_session(
    request: QuickSummarySessionRequest, case_id: str, actor: PreviewActor
) -> QuickSummarySessionResponse:
    return await post_quick_summary_session(case_id, request, actor)


@app.patch("/", response_model=CaseDashboardResponse)
@app.patch("/api/cases/dashboard", response_model=CaseDashboardResponse)
async def patch_by_scope(
    case_id: str,
    actor: PreviewActor,
    response: Response,
    scope: str | None = None,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> CaseDashboardResponse:
    """scope=profile이면 프로필 수정, 그 외(schedule/미지정)는 일정 수정."""
    try:
        if scope == "profile":
            return await patch_case_profile(case_id, CaseProfileUpdateRequest(**payload), actor)
        return await patch_case_schedule(case_id, CaseScheduleUpdateRequest(**payload), actor)
    except ValidationError as error:
        raise _validation_error(error)


@app.patch("/api/cases/{case_id}/schedule", response_model=CaseDashboardResponse)
async def schedule(request: CaseScheduleUpdateRequest, case_id: str, actor: PreviewActor) -> CaseDashboardResponse:
    return await patch_case_schedule(case_id, request, actor)


@app.patch("/api/cases/{case_id}/profile", response_model=CaseDashboardResponse)
async def profile(request: CaseProfileUpdateRequest, case_id: str, actor: PreviewActor) -> CaseDashboardResponse:
    return await patch_case_profile(case_id, request, actor)
