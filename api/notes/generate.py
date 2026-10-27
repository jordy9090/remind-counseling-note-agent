"""Vercel serverless wrapper for note generation and the public quick summary.

The quick summary and the de-identification preview share this function to stay
under Vercel's 12-function limit. vercel.json rewrites /api/notes/quick-summary →
/api/notes/generate?scope=quick and /api/notes/deidentification-preview →
/api/notes/generate?scope=deid-preview; QuickSummaryPathMiddleware routes them.
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
from app.api.routes.notes import (  # noqa: E402
    _run_pipeline_with_stub_fallback,
    run_deidentification_preview,
    run_quick_summary,
)
from app.services.deidentification_preview import (  # noqa: E402
    DeidentificationPreviewRequest,
    DeidentificationPreviewResponse,
)
from app.schemas.note import GenerateNoteResponse, SessionInput  # noqa: E402
from app.services.quick_summary import QuickSummaryRequest  # noqa: E402

QUICK_SUMMARY_PATH = "/api/notes/quick-summary"
DEID_PREVIEW_PATH = "/api/notes/deidentification-preview"
SCOPE_PATHS = {"scope=quick": QUICK_SUMMARY_PATH, "scope=deid-preview": DEID_PREVIEW_PATH}


class QuickSummaryPathMiddleware:
    """Route ``?scope=quick`` / ``?scope=deid-preview`` (rewritten URLs) to their own handlers."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("path") in {"/", "/api/notes/generate"}:
            params = scope.get("query_string", b"").decode("latin-1").split("&")
            path = next((target for param, target in SCOPE_PATHS.items() if param in params), None)
            if path:
                scope = {**scope, "path": path, "raw_path": path.encode()}
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


@app.post(QUICK_SUMMARY_PATH, response_model=GenerateNoteResponse)
async def quick_summary(
    payload: QuickSummaryRequest,
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> GenerateNoteResponse:
    return run_quick_summary(payload, request=request, authorization=authorization)


@app.post(DEID_PREVIEW_PATH, response_model=DeidentificationPreviewResponse)
async def deidentification_preview(
    payload: DeidentificationPreviewRequest,
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> DeidentificationPreviewResponse:
    return run_deidentification_preview(payload, request=request, authorization=authorization)
