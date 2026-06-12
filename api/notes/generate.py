"""Vercel serverless wrapper for the Re:mind note generation endpoint."""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI

ROOT_DIR = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "backend" / "app").exists()
)
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.routes.notes import _run_pipeline_with_stub_fallback  # noqa: E402
from app.schemas.note import GenerateNoteResponse, SessionInput  # noqa: E402

app = FastAPI(title="Re:mind Note API")


@app.post("/", response_model=GenerateNoteResponse)
@app.post("/api/notes/generate", response_model=GenerateNoteResponse)
async def generate_note(session_input: SessionInput) -> GenerateNoteResponse:
    return _run_pipeline_with_stub_fallback(session_input)
