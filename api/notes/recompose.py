"""Vercel serverless wrapper for checklist-specific note recomposition."""
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
from app.schemas.note import RecomposeNoteRequest, RecomposeNoteResponse  # noqa: E402
from app.api.routes.notes import recompose_note_draft as reviewed_recompose

app = FastAPI(title="Re:mind Note Recompose API")
PreviewActor = Annotated[str, Depends(require_preview_access)]


@app.post("/", response_model=RecomposeNoteResponse)
@app.post("/api/notes/recompose", response_model=RecomposeNoteResponse)
async def recompose_note_draft(
    request: RecomposeNoteRequest,
    actor: PreviewActor,
    review_receipt: str = Header(default="", alias="X-Review-Receipt"),
) -> RecomposeNoteResponse:
    return await reviewed_recompose(request, actor, review_receipt)
