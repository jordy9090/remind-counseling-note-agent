"""Routes for exporting finalized counseling documents."""
from __future__ import annotations

from io import BytesIO

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.schemas.document import DocumentCapabilitiesResponse, DocumentExportRequest
from app.services.document_export import (
    DocumentExportRuntimeError,
    DocumentExportService,
    DocumentExportValidationError,
    UnsupportedExportFormat,
)

router = APIRouter(prefix="/api/documents", tags=["documents"])
document_export_service = DocumentExportService()
AuthenticatedUser = Annotated[str, Depends(require_preview_access)]


@router.post("/export")
async def export_document(request: DocumentExportRequest, actor: AuthenticatedUser) -> StreamingResponse:
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


@router.get("/capabilities", response_model=DocumentCapabilitiesResponse)
async def get_document_capabilities(actor: AuthenticatedUser) -> dict[str, dict[str, str | bool | None]]:
    """Return server-side export runtime capabilities."""
    return await run_in_threadpool(document_export_service.capabilities)
from app.api.security import require_preview_access
