"""Routes for extracting uploaded counseling document materials."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from app.schemas.material import DocumentExtractionResponse
from app.services.document_extraction import DocumentExtractionError, DocumentExtractionService
from app.services.upload_validation import UploadValidationError, cleanup_temp_file, persist_upload_to_temp

router = APIRouter(prefix="/api/materials", tags=["materials"])
document_extraction_service = DocumentExtractionService()
AuthenticatedUser = Annotated[str, Depends(require_preview_access)]


@router.post("/documents/extract", response_model=DocumentExtractionResponse)
async def extract_document_material(
    response: Response,
    actor: AuthenticatedUser,
    file: UploadFile = File(...),
) -> DocumentExtractionResponse:
    """Extract text from a temporary document upload without storing raw bytes."""
    validated = None
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    try:
        validated = await persist_upload_to_temp(file, "document")
        return await run_in_threadpool(document_extraction_service.extract, validated)
    except UploadValidationError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    except DocumentExtractionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        if validated is not None:
            cleanup_temp_file(validated.temp_path)
from app.api.security import require_preview_access
