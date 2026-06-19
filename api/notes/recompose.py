"""Vercel serverless wrapper for checklist-specific note recomposition."""
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

from app.schemas.note import RecomposeNoteRequest, RecomposeNoteResponse  # noqa: E402
from app.services.recompose_cache import recompose_note_with_cache  # noqa: E402

app = FastAPI(title="Re:mind Note Recompose API")


@app.post("/", response_model=RecomposeNoteResponse)
@app.post("/api/notes/recompose", response_model=RecomposeNoteResponse)
async def recompose_note_draft(request: RecomposeNoteRequest) -> RecomposeNoteResponse:
    try:
        return recompose_note_with_cache(request)
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"요약초안 재구성 중 오류가 발생했습니다: {str(error)}",
        ) from error
