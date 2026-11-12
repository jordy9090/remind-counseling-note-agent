"""Vercel serverless wrapper for note confirmation endpoint."""
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
from app.schemas.note import ConfirmGeneratedNoteRequest, ConfirmGeneratedNoteResponse  # noqa: E402
from app.api.routes.notes import confirm_note as reviewed_confirm

app = FastAPI(title="Re:mind Note Confirmation API")
PreviewActor = Annotated[str, Depends(require_preview_access)]


@app.post("/", response_model=ConfirmGeneratedNoteResponse)
@app.post("/api/notes/confirm", response_model=ConfirmGeneratedNoteResponse)
async def confirm_note(
    request: ConfirmGeneratedNoteRequest,
    actor: PreviewActor,
    review_receipt: str = Header(default="", alias="X-Review-Receipt"),
) -> ConfirmGeneratedNoteResponse:
    return await reviewed_confirm(request, actor, review_receipt)
