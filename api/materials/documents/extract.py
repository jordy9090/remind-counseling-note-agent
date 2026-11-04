"""Vercel serverless wrapper for authenticated document extraction."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, HTTPException, Response, UploadFile
from starlette.concurrency import run_in_threadpool

ROOT_DIR = next(parent for parent in Path(__file__).resolve().parents if (parent / "backend" / "app").exists())
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.security import require_preview_access  # noqa: E402
from app.api.routes.audio import router as audio_router  # noqa: E402
from app.schemas.material import DocumentExtractionResponse  # noqa: E402
from app.services.document_extraction import DocumentExtractionError, DocumentExtractionService  # noqa: E402
from app.services.upload_validation import (  # noqa: E402
    UploadValidationError,
    cleanup_temp_file,
    persist_upload_to_temp,
)

app = FastAPI(title="Re:mind Material Extraction API")
app.include_router(audio_router)


@app.middleware("http")
async def route_audio(request, call_next):
    # Share one function to stay within the project's serverless function limit.
    audio_path = request.query_params.get("audio_path")
    if audio_path in {"capabilities", "transcribe", "deidentify"}:
        request.scope["path"] = f"/api/audio/{audio_path}"
    return await call_next(request)

AuthenticatedUser = Annotated[str, Depends(require_preview_access)]
service = DocumentExtractionService()


@app.post("/", response_model=DocumentExtractionResponse)
@app.post("/api/materials/documents/extract", response_model=DocumentExtractionResponse)
async def extract_document_material(
    response: Response,
    actor: AuthenticatedUser,
    file: UploadFile = File(...),
) -> DocumentExtractionResponse:
    validated = None
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    try:
        validated = await persist_upload_to_temp(file, "document")
        return await run_in_threadpool(service.extract, validated)
    except UploadValidationError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    except DocumentExtractionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail="문서 처리 중 서버 오류가 발생했습니다.") from error
    finally:
        if validated is not None:
            cleanup_temp_file(validated.temp_path)
