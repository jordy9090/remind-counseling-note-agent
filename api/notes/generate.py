"""Vercel serverless wrapper for note generation and the public quick summary.

The quick summary shares this function to stay under Vercel's 12-function limit.
vercel.json rewrites /api/notes/quick-summary → /api/notes/generate?scope=quick,
and QuickSummaryPathMiddleware routes that request to the quick-summary handler.
"""
from __future__ import annotations

import sys
from pathlib import Path

from typing import Annotated
from fastapi import Depends, FastAPI, Header, Request

ROOT_DIR = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "backend" / "app").exists()
)
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.security import require_preview_access  # noqa: E402
from app.api.routes.notes import _run_pipeline_with_stub_fallback, run_quick_summary  # noqa: E402
from app.schemas.note import GenerateNoteResponse, SessionInput  # noqa: E402
from app.services.quick_summary import QuickSummaryRequest, QuickSummaryResponse  # noqa: E402

QUICK_SUMMARY_PATH = "/api/notes/quick-summary"


class QuickSummaryPathMiddleware:
    """Route ``?scope=quick`` requests (the rewritten quick-summary URL) to their own handler."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("path") in {"/", "/api/notes/generate"}:
            query = scope.get("query_string", b"").decode("latin-1")
            if "scope=quick" in query.split("&"):
                scope = {**scope, "path": QUICK_SUMMARY_PATH, "raw_path": QUICK_SUMMARY_PATH.encode()}
        await self.app(scope, receive, send)

app = FastAPI(title="Re:mind Note API")
app.add_middleware(QuickSummaryPathMiddleware)
PreviewActor = Annotated[str, Depends(require_preview_access)]


@app.post("/", response_model=GenerateNoteResponse)
@app.post("/api/notes/generate", response_model=GenerateNoteResponse)
async def generate_note(
    session_input: SessionInput,
    actor: PreviewActor,
) -> GenerateNoteResponse:
    return _run_pipeline_with_stub_fallback(session_input, actor=actor)


@app.post(QUICK_SUMMARY_PATH, response_model=QuickSummaryResponse)
async def quick_summary(
    payload: QuickSummaryRequest,
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> QuickSummaryResponse:
    return run_quick_summary(payload, request=request, authorization=authorization)
