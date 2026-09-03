"""Routes for exporting finalized counseling documents."""
from __future__ import annotations

from io import BytesIO

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.api.security import require_preview_access
from app.schemas.document import DocumentCapabilitiesResponse, DocumentExportRequest
from app.services.document_export import (
    DocumentExportRuntimeError,
    DocumentExportService,
    DocumentExportValidationError,
    UnsupportedExportFormat,
)
from app.services.supabase_storage import record_document_export

router = APIRouter(prefix="/api/documents", tags=["documents"])
document_export_service = DocumentExportService()
AuthenticatedUser = Annotated[str, Depends(require_preview_access)]


@router.post("/export")
async def export_document(request: DocumentExportRequest, actor: AuthenticatedUser) -> StreamingResponse:
    """Generate a downloadable document from the latest final-document draft."""
    def _log_export(status: str, error_message: str | None = None) -> None:
        # 대시보드용 변환 이력 — 실패해도 export 응답에는 영향을 주지 않는다.
        record_document_export(
            case_id=request.case_id,
            session_number=request.session_number or None,
            document_type=str(request.document_type),
            export_format=str(request.format),
            title=request.title,
            status=status,
            error=error_message,
            actor=actor,
        )

    try:
        result = await run_in_threadpool(document_export_service.export, request)
    except (DocumentExportValidationError, UnsupportedExportFormat) as error:
        _log_export("failed", str(error))
        raise HTTPException(status_code=422, detail=str(error)) from error
    except DocumentExportRuntimeError as error:
        _log_export("failed", str(error))
        raise HTTPException(status_code=500, detail=str(error)) from error

    _log_export("completed")
    return StreamingResponse(
        BytesIO(result.content),
        media_type=result.content_type,
        headers=result.headers,
    )


@router.get("/capabilities", response_model=DocumentCapabilitiesResponse)
async def get_document_capabilities(actor: AuthenticatedUser) -> dict[str, dict[str, str | bool | None]]:
    """Return server-side export runtime capabilities."""
    return await run_in_threadpool(document_export_service.capabilities)
