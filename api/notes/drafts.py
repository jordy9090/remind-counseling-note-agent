"""Vercel serverless wrapper for temporary note draft storage."""
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

from app.schemas.note import (  # noqa: E402
    TemporaryDraftRecord,
    TemporaryDraftSaveRequest,
    TemporaryDraftSaveResponse,
)
from app.services.draft_store import get_temporary_draft, list_temporary_drafts, save_temporary_draft  # noqa: E402

app = FastAPI(title="Re:mind Temporary Draft API")


@app.post("/", response_model=TemporaryDraftSaveResponse)
@app.post("/api/notes/drafts", response_model=TemporaryDraftSaveResponse)
async def save_note_draft(draft: TemporaryDraftSaveRequest) -> TemporaryDraftSaveResponse:
    return save_temporary_draft(draft)


@app.get("/", response_model=list[TemporaryDraftRecord])
@app.get("/api/notes/drafts", response_model=list[TemporaryDraftRecord])
async def list_note_drafts(case_id: str | None = None) -> list[TemporaryDraftRecord]:
    return list_temporary_drafts(case_id=case_id)


@app.get("/{draft_id}", response_model=TemporaryDraftRecord)
@app.get("/api/notes/drafts/{draft_id}", response_model=TemporaryDraftRecord)
async def get_note_draft(draft_id: str) -> TemporaryDraftRecord:
    draft = get_temporary_draft(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="임시저장 초안을 찾을 수 없습니다.")
    return draft
