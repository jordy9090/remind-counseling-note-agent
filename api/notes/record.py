"""Vercel entry point for the shared, ownership-checked note detail route."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Path as PathParameter, Query, Response

ROOT_DIR = next(parent for parent in Path(__file__).resolve().parents if (parent / "backend" / "app").exists())
if str(ROOT_DIR / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "backend"))

from app.api.security import require_preview_access
from app.api.routes.notes import delete_note_session_input, get_note_record, get_note_storage_policy
from app.schemas.note import GeneratedNoteRecord, SessionInputDeletionResponse
from app.schemas.storage_policy import NoteStoragePolicy

app = FastAPI(title="Re:mind Note Record API")
PreviewActor = Annotated[str, Depends(require_preview_access)]


@app.get("/", response_model=GeneratedNoteRecord | NoteStoragePolicy)
@app.get("/api/notes/record", response_model=GeneratedNoteRecord | NoteStoragePolicy)
async def record_or_policy(
    actor: PreviewActor,
    response: Response,
    note_id: Annotated[str | None, Query(max_length=36)] = None,
    scope: Literal["storage-policy"] | None = None,
) -> GeneratedNoteRecord | NoteStoragePolicy:
    if scope == "storage-policy":
        if note_id is not None:
            raise HTTPException(status_code=422, detail="A storage-policy request cannot include a note ID.")
        return await get_note_storage_policy(actor, response)
    if note_id is None:
        raise HTTPException(status_code=422, detail="A note ID is required.")
    return await get_note_record(note_id, actor, response)


@app.get("/api/notes/storage-policy", response_model=NoteStoragePolicy)
async def storage_policy(actor: PreviewActor, response: Response) -> NoteStoragePolicy:
    return await get_note_storage_policy(actor, response)


@app.get("/api/notes/records/{note_id}", response_model=GeneratedNoteRecord)
async def record(
    note_id: Annotated[str, PathParameter(max_length=36)],
    actor: PreviewActor,
    response: Response,
) -> GeneratedNoteRecord:
    return await get_note_record(note_id, actor, response)


# 회기별 원문 삭제 shares this function (Vercel 12-function limit). vercel.json rewrites
# /api/notes/records/:note_id/input-deletion to /api/notes/record?note_id=...&scope=input-deletion.
@app.post("/", response_model=SessionInputDeletionResponse)
@app.post("/api/notes/record", response_model=SessionInputDeletionResponse)
async def record_input_deletion(
    actor: PreviewActor,
    response: Response,
    note_id: Annotated[str | None, Query(max_length=36)] = None,
    scope: Literal["input-deletion"] | None = None,
) -> SessionInputDeletionResponse:
    if scope != "input-deletion" or note_id is None:
        raise HTTPException(status_code=422, detail="An input-deletion request needs a note ID.")
    return await delete_note_session_input(note_id, actor, response)


@app.post("/api/notes/records/{note_id}/input-deletion", response_model=SessionInputDeletionResponse)
async def input_deletion(
    note_id: Annotated[str, PathParameter(max_length=36)],
    actor: PreviewActor,
    response: Response,
) -> SessionInputDeletionResponse:
    return await delete_note_session_input(note_id, actor, response)
