"""Vercel serverless wrapper for note confirmation endpoint."""
from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException

ROOT_DIR = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "backend" / "app").exists()
)
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.security import require_preview_access  # noqa: E402
from app.schemas.note import ConfirmGeneratedNoteRequest, ConfirmGeneratedNoteResponse  # noqa: E402
from app.services.supabase_storage import NoteConfirmationError, confirm_generated_note  # noqa: E402

app = FastAPI(title="Re:mind Note Confirmation API")
PreviewActor = Annotated[str, Depends(require_preview_access)]


@app.post("/", response_model=ConfirmGeneratedNoteResponse)
@app.post("/api/notes/confirm", response_model=ConfirmGeneratedNoteResponse)
async def confirm_note(
    request: ConfirmGeneratedNoteRequest,
    actor: PreviewActor,
) -> ConfirmGeneratedNoteResponse:
    try:
        return confirm_generated_note(request, actor=actor)
    except NoteConfirmationError as error:
        raise HTTPException(status_code=error.status_code, detail=error.message)
    except HTTPException:
        raise
    except Exception as error:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Note confirmation failed: {str(error)}")
