"""Vercel serverless wrapper for document export capabilities."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI
from starlette.concurrency import run_in_threadpool

ROOT_DIR = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "backend" / "app").exists()
)
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.security import require_preview_access  # noqa: E402
from app.schemas.document import DocumentCapabilitiesResponse  # noqa: E402
from app.services.document_export import DocumentExportService  # noqa: E402

app = FastAPI(title="Re:mind Document Capabilities API")
PreviewActor = Annotated[str, Depends(require_preview_access)]
document_export_service = DocumentExportService()


@app.get("/")
@app.get("/api/documents/capabilities", response_model=DocumentCapabilitiesResponse)
async def get_document_capabilities(
    actor: PreviewActor,
) -> DocumentCapabilitiesResponse:
    """Return server-side export runtime capabilities."""
    return await run_in_threadpool(document_export_service.capabilities)
