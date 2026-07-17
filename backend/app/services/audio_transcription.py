"""Audio transcription service interface and optional faster-whisper adapter."""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from uuid import uuid4

from app.schemas.audio import AudioCapabilitiesResponse, AudioCapability, AudioSegment, AudioTranscriptionResponse
from app.services.upload_validation import ValidatedUpload


UNAVAILABLE_REASON = (
    "음성 자동 축어록 런타임이 비활성화되어 있습니다. "
    "ENABLE_AUDIO_TRANSCRIPTION=1 및 faster-whisper 런타임을 설정해야 합니다."
)


class AudioTranscriptionUnavailable(Exception):
    """Raised when transcription is not configured on this runtime."""

    def __init__(self, reason: str = UNAVAILABLE_REASON) -> None:
        super().__init__(reason)
        self.reason = reason


class AudioTranscriptionRuntimeError(Exception):
    """Raised when an enabled transcription runtime fails safely."""


class AudioTranscriptionService(ABC):
    """Interface for real audio transcription implementations."""

    @abstractmethod
    def transcribe(
        self,
        upload: ValidatedUpload,
        language: str | None = None,
        task: str = "transcribe",
    ) -> AudioTranscriptionResponse:
        """Return a real transcription or raise AudioTranscriptionUnavailable."""


class UnavailableAudioTranscriptionService(AudioTranscriptionService):
    def __init__(self, reason: str = UNAVAILABLE_REASON) -> None:
        self.reason = reason

    def transcribe(
        self,
        upload: ValidatedUpload,
        language: str | None = None,
        task: str = "transcribe",
    ) -> AudioTranscriptionResponse:
        raise AudioTranscriptionUnavailable(self.reason)


class FasterWhisperTranscriptionService(AudioTranscriptionService):
    """Opt-in faster-whisper adapter. Model download is never triggered unless enabled."""

    def __init__(self) -> None:
        self._model = None

    def transcribe(
        self,
        upload: ValidatedUpload,
        language: str | None = None,
        task: str = "transcribe",
    ) -> AudioTranscriptionResponse:
        try:
            from faster_whisper import WhisperModel
        except ImportError as error:
            raise AudioTranscriptionUnavailable("faster-whisper 패키지가 설치되어 있지 않습니다.") from error

        try:
            if self._model is None:
                self._model = WhisperModel(
                    os.getenv("WHISPER_MODEL_SIZE", "large-v3"),
                    device=normalize_auto(os.getenv("WHISPER_DEVICE", "auto")),
                    compute_type=normalize_auto(os.getenv("WHISPER_COMPUTE_TYPE", "auto")),
                )

            segments_iter, info = self._model.transcribe(
                str(upload.temp_path),
                language=language or None,
                task=task,
            )
        except AudioTranscriptionUnavailable:
            raise
        except Exception as error:
            raise AudioTranscriptionRuntimeError("음성 축어록 생성 중 오류가 발생했습니다.") from error

        segments = [
            AudioSegment(id=index, start=float(segment.start), end=float(segment.end), text=segment.text.strip())
            for index, segment in enumerate(segments_iter, start=1)
            if segment.text.strip()
        ]
        transcript_text = "\n".join(segment.text for segment in segments)
        duration_seconds = max((segment.end for segment in segments), default=getattr(info, "duration", None))
        return AudioTranscriptionResponse(
            transcription_id=f"transcription_{uuid4().hex}",
            filename=upload.filename,
            duration_seconds=float(duration_seconds) if duration_seconds is not None else None,
            language=getattr(info, "language", None) or language,
            segments=segments,
            transcript_text=transcript_text,
            warnings=[],
        )


def get_audio_capabilities() -> AudioCapabilitiesResponse:
    transcription = get_transcription_capability()
    return AudioCapabilitiesResponse(
        upload=AudioCapability(available=True),
        transcription=transcription,
        speaker_diarization=AudioCapability(
            available=False,
            reason="화자 분리 기능은 이번 MVP 범위에 포함되어 있지 않습니다.",
        ),
    )


def get_transcription_service() -> AudioTranscriptionService:
    capability = get_transcription_capability()
    if not capability.available:
        return UnavailableAudioTranscriptionService(capability.reason or UNAVAILABLE_REASON)
    return FasterWhisperTranscriptionService()


def get_transcription_capability() -> AudioCapability:
    if os.getenv("ENABLE_AUDIO_TRANSCRIPTION", "0") != "1":
        return AudioCapability(available=False, reason=UNAVAILABLE_REASON)
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return AudioCapability(available=False, reason="faster-whisper 패키지가 설치되어 있지 않습니다.")
    return AudioCapability(available=True)


def normalize_auto(value: str) -> str:
    return "auto" if not value else value
