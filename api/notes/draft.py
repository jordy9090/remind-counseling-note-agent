"""Vercel serverless wrapper for loading one user-owned note draft."""
from __future__ import annotations

import sys
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
from app.schemas.note import TemporaryDraftRecord  # noqa: E402
from app.services.draft_store import get_temporary_draft  # noqa: E402

app = FastAPI(title="Re:mind Temporary Draft Detail API")
PreviewActor = Annotated[str, Depends(require_preview_access)]


@app.get("/", response_model=TemporaryDraftRecord)
@app.get("/api/notes/draft", response_model=TemporaryDraftRecord)
@app.get("/api/notes/drafts/{draft_id}", response_model=TemporaryDraftRecord)
async def get_note_draft(draft_id: str, actor: PreviewActor) -> TemporaryDraftRecord:
    """Return a draft only when it belongs to the authenticated user."""
    draft = get_temporary_draft(draft_id, actor=actor)
    if draft is None:
        raise HTTPException(status_code=404, detail="임시저장 초안을 찾을 수 없습니다.")
    return draft
