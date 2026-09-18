"""Vercel serverless wrapper for client profile updates (PATCH /api/cases/{case_id}/profile)."""
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
from app.api.routes.cases import patch_case_profile  # noqa: E402
from app.schemas.note import CaseDashboardResponse, CaseProfileUpdateRequest  # noqa: E402

app = FastAPI(title="Re:mind Client Profile API")
PreviewActor = Annotated[str, Depends(require_preview_access)]


# vercel.json rewrites /api/cases/:case_id/profile → /api/cases/profile?case_id=:case_id
@app.patch("/", response_model=CaseDashboardResponse)
@app.patch("/api/cases/profile", response_model=CaseDashboardResponse)
@app.patch("/api/cases/{case_id}/profile", response_model=CaseDashboardResponse)
async def profile(
    request: CaseProfileUpdateRequest,
    case_id: str,
    actor: PreviewActor,
) -> CaseDashboardResponse:
    return await patch_case_profile(case_id, request, actor)
