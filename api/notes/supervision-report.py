"""Vercel serverless wrapper for the supervision report draft endpoint."""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException

ROOT_DIR = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "backend" / "app").exists()
)
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.graph.supervision_report import run_supervision_report_pipeline  # noqa: E402
from app.schemas.note import SupervisionReportDraft, SupervisionReportRequest  # noqa: E402

app = FastAPI(title="Re:mind Supervision Report API")


@app.post("/", response_model=SupervisionReportDraft)
@app.post("/api/notes/supervision-report", response_model=SupervisionReportDraft)
async def generate_supervision_report(request: SupervisionReportRequest) -> SupervisionReportDraft:
    try:
        return run_supervision_report_pipeline(request)
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"수퍼비전 보고서 초안 생성 중 오류가 발생했습니다: {str(error)}",
        ) from error
