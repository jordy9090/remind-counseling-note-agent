"""Vercel entry point for the shared, ownership-checked note detail route."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Response

ROOT_DIR = next(parent for parent in Path(__file__).resolve().parents if (parent / "backend" / "app").exists())
if str(ROOT_DIR / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "backend"))

from app.api.security import require_preview_access
from app.api.routes.notes import get_note_record
from app.schemas.note import GeneratedNoteRecord

app = FastAPI(title="Re:mind Note Record API")
PreviewActor = Annotated[str, Depends(require_preview_access)]


@app.get("/", response_model=GeneratedNoteRecord)
@app.get("/api/notes/record", response_model=GeneratedNoteRecord)
@app.get("/api/notes/records/{note_id}", response_model=GeneratedNoteRecord)
async def record(note_id: str, actor: PreviewActor, response: Response) -> GeneratedNoteRecord:
    return await get_note_record(note_id, actor, response)
