"""Vercel serverless wrapper for the owned case list endpoint (GET /api/cases)."""
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
from app.api.routes.cases import get_case_list  # noqa: E402
from app.schemas.note import CaseListResponse  # noqa: E402

app = FastAPI(title="Re:mind Case List API")
PreviewActor = Annotated[str, Depends(require_preview_access)]


@app.get("/", response_model=CaseListResponse)
@app.get("/api/cases", response_model=CaseListResponse)
@app.get("/api/cases/list", response_model=CaseListResponse)
async def case_list(actor: PreviewActor) -> CaseListResponse:
    return await get_case_list(actor)
