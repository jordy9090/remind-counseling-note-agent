"""Routes for exporting finalized counseling documents."""
from __future__ import annotations

from io import BytesIO

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.schemas.document import DocumentExportRequest
from app.services.document_export import (
    DocumentExportRuntimeError,
    DocumentExportService,
    DocumentExportValidationError,
    UnsupportedExportFormat,
)

router = APIRouter(prefix="/api/documents", tags=["documents"])
document_export_service = DocumentExportService()


@router.post("/export")
async def export_document(request: DocumentExportRequest) -> StreamingResponse:
    """Generate a downloadable document from the latest final-document draft."""
    try:
        result = document_export_service.export(request)
    except (DocumentExportValidationError, UnsupportedExportFormat) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except DocumentExportRuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error

    return StreamingResponse(
        BytesIO(result.content),
        media_type=result.content_type,
        headers=result.headers,
    )
