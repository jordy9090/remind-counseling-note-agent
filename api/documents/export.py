"""Vercel serverless wrapper for exporting finalized counseling documents."""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

ROOT_DIR = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "backend" / "app").exists()
)
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.security import require_preview_access  # noqa: E402
from app.schemas.document import DocumentExportRequest  # noqa: E402
from app.services.document_export import (  # noqa: E402
    DocumentExportRuntimeError,
    DocumentExportService,
    DocumentExportValidationError,
    UnsupportedExportFormat,
)

app = FastAPI(title="Re:mind Document Export API")
PreviewActor = Annotated[str, Depends(require_preview_access)]
document_export_service = DocumentExportService()


@app.post("/")
@app.post("/api/documents/export")
async def export_document(
    request: DocumentExportRequest,
    actor: PreviewActor,
) -> StreamingResponse:
    """Generate a downloadable document from the latest final-document draft."""
    try:
        result = await run_in_threadpool(document_export_service.export, request)
    except (DocumentExportValidationError, UnsupportedExportFormat) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except DocumentExportRuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error

    return StreamingResponse(
        BytesIO(result.content),
        media_type=result.content_type,
        headers=result.headers,
    )
