"""Vercel serverless wrapper for the case dashboard and schedule endpoints."""
from __future__ import annotations

import sys
from pathlib import Path

from typing import Annotated
from fastapi import Depends, FastAPI

ROOT_DIR = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "backend" / "app").exists()
)
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.security import require_preview_access  # noqa: E402
from app.api.routes.cases import get_case_dashboard, patch_case_schedule  # noqa: E402
from app.schemas.note import CaseDashboardResponse, CaseScheduleUpdateRequest  # noqa: E402

app = FastAPI(title="Re:mind Case Dashboard API")
PreviewActor = Annotated[str, Depends(require_preview_access)]


@app.get("/", response_model=CaseDashboardResponse)
@app.get("/api/cases/dashboard", response_model=CaseDashboardResponse)
@app.get("/api/cases/{case_id}/dashboard", response_model=CaseDashboardResponse)
async def dashboard(case_id: str, actor: PreviewActor) -> CaseDashboardResponse:
    return await get_case_dashboard(case_id, actor)


@app.patch("/", response_model=CaseDashboardResponse)
@app.patch("/api/cases/dashboard", response_model=CaseDashboardResponse)
@app.patch("/api/cases/{case_id}/schedule", response_model=CaseDashboardResponse)
async def schedule(
    request: CaseScheduleUpdateRequest,
    case_id: str,
    actor: PreviewActor,
) -> CaseDashboardResponse:
    return await patch_case_schedule(case_id, request, actor)
