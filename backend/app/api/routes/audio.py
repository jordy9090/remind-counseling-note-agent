"""Routes for audio upload capabilities and optional transcription."""
from __future__ import annotations

import re
from functools import partial
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from app.api.security import require_preview_access
from app.schemas.audio import AudioCapabilitiesResponse, AudioTranscriptionResponse
from app.services.audio_transcription import (
    AudioDurationLimitError,
    AudioNoSpeechDetectedError,
    AudioTranscriptionBusyError,
    AudioTranscriptionRuntimeError,
    AudioTranscriptionUnavailable,
    get_audio_capabilities,
    get_transcription_service,
)
from app.services.upload_validation import UploadValidationError, cleanup_temp_file, persist_upload_to_temp

router = APIRouter(prefix="/api/audio", tags=["audio"])
AuthenticatedUser = Annotated[str, Depends(require_preview_access)]


@router.get("/capabilities", response_model=AudioCapabilitiesResponse)
async def audio_capabilities(response: Response, actor: AuthenticatedUser) -> AudioCapabilitiesResponse:
    """Return upload/transcription runtime capability status."""
    response.headers["Cache-Control"] = "no-store"
    return get_audio_capabilities()


@router.post("/transcribe", response_model=AudioTranscriptionResponse)
async def transcribe_audio(
    response: Response,
    actor: AuthenticatedUser,
    file: UploadFile = File(...),
    language: str | None = Form(default=None),
    task: str = Form(default="transcribe"),
    expected_speakers: int = Form(default=2),
) -> AudioTranscriptionResponse:
    """Transcribe a temporary audio upload when the opt-in runtime is available."""
    validated = None
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    try:
        validate_audio_request(language, task, expected_speakers)
        validated = await persist_upload_to_temp(file, "audio")
        service = get_transcription_service()
        transcribe = partial(
            service.transcribe,
            validated,
            language=language,
            task=task,
            expected_speakers=expected_speakers,
        )
        return await run_in_threadpool(transcribe)
    except UploadValidationError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    except (AudioNoSpeechDetectedError, AudioDurationLimitError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except AudioTranscriptionBusyError as error:
        raise HTTPException(status_code=429, detail=str(error)) from error
    except AudioTranscriptionUnavailable as error:
        raise HTTPException(status_code=503, detail=error.reason) from error
    except AudioTranscriptionRuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    finally:
        if validated is not None:
            cleanup_temp_file(validated.temp_path)


def validate_audio_request(language: str | None, task: str, expected_speakers: int) -> None:
    if task not in {"transcribe", "translate"}:
        raise HTTPException(status_code=422, detail="task는 transcribe 또는 translate만 사용할 수 있습니다.")
    if language and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{1,9}", language):
        raise HTTPException(status_code=422, detail="language는 2~10자의 안전한 언어 코드여야 합니다.")
    if not 1 <= expected_speakers <= 4:
        raise HTTPException(status_code=422, detail="expected_speakers는 1~4 사이여야 합니다.")
