"""Vercel serverless wrapper for the supervision report draft endpoint."""
from __future__ import annotations

import sys
from pathlib import Path

from typing import Annotated
from fastapi import Depends, FastAPI, Header

ROOT_DIR = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "backend" / "app").exists()
)
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.security import require_preview_access  # noqa: E402
from app.graph.supervision_report import run_supervision_report_pipeline  # noqa: E402
from app.schemas.note import SupervisionReportDraft, SupervisionReportRequest  # noqa: E402
from app.api.routes.notes import generate_supervision_report as reviewed_supervision

app = FastAPI(title="Re:mind Supervision Report API")
PreviewActor = Annotated[str, Depends(require_preview_access)]


@app.post("/", response_model=SupervisionReportDraft)
@app.post("/api/notes/supervision-report", response_model=SupervisionReportDraft)
async def generate_supervision_report(
    request: SupervisionReportRequest,
    actor: PreviewActor,
    review_receipt: str = Header(default="", alias="X-Review-Receipt"),
) -> SupervisionReportDraft:
    return await reviewed_supervision(request, actor, review_receipt)
