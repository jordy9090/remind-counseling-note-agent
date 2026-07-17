"""Audio transcription service interface and optional faster-whisper adapter."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
import os
from threading import Lock
from typing import Any
from uuid import uuid4

from app.schemas.audio import AudioCapabilitiesResponse, AudioCapability, AudioSegment, AudioTranscriptionResponse
from app.services.upload_validation import ValidatedUpload


UNAVAILABLE_REASON = (
    "음성 자동 축어록 런타임이 비활성화되어 있습니다. "
    "ENABLE_AUDIO_TRANSCRIPTION=1 및 faster-whisper 런타임을 설정해야 합니다."
)


@dataclass(frozen=True)
class WhisperRuntimeConfig:
    model_size: str
    device: str
    compute_type: str


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

    def __init__(
        self,
        config: WhisperRuntimeConfig | None = None,
        model_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.config = config or current_whisper_config()
        self._model_factory = model_factory
        self._model = None
        self._model_lock = Lock()

    def transcribe(
        self,
        upload: ValidatedUpload,
        language: str | None = None,
        task: str = "transcribe",
    ) -> AudioTranscriptionResponse:
        try:
            model = self._get_model()
            segments_iter, info = model.transcribe(
                str(upload.temp_path),
                language=language or None,
                task=task,
            )
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
        except AudioTranscriptionUnavailable:
            raise
        except Exception as error:
            raise AudioTranscriptionRuntimeError("음성 축어록 생성 중 오류가 발생했습니다.") from error

    def _get_model(self):
        if self._model is not None:
            return self._model
        with self._model_lock:
            if self._model is None:
                factory = self._model_factory or get_whisper_model_factory()
                self._model = factory(
                    self.config.model_size,
                    device=self.config.device,
                    compute_type=self.config.compute_type,
                )
        return self._model


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
    global _transcription_service_cache

    capability = get_transcription_capability()
    if not capability.available:
        return UnavailableAudioTranscriptionService(capability.reason or UNAVAILABLE_REASON)
    config = current_whisper_config()
    with _transcription_service_lock:
        if _transcription_service_cache and _transcription_service_cache[0] == config:
            return _transcription_service_cache[1]
        service = FasterWhisperTranscriptionService(config=config, model_factory=_whisper_model_factory_override)
        _transcription_service_cache = (config, service)
        return service


def get_transcription_capability() -> AudioCapability:
    if os.getenv("ENABLE_AUDIO_TRANSCRIPTION", "0") != "1":
        return AudioCapability(available=False, reason=UNAVAILABLE_REASON)
    if _whisper_model_factory_override is not None:
        return AudioCapability(available=True)
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return AudioCapability(available=False, reason="faster-whisper 패키지가 설치되어 있지 않습니다.")
    return AudioCapability(available=True)


def normalize_auto(value: str) -> str:
    return "auto" if not value else value


def current_whisper_config() -> WhisperRuntimeConfig:
    return WhisperRuntimeConfig(
        model_size=os.getenv("WHISPER_MODEL_SIZE", "large-v3"),
        device=normalize_auto(os.getenv("WHISPER_DEVICE", "auto")),
        compute_type=normalize_auto(os.getenv("WHISPER_COMPUTE_TYPE", "auto")),
    )


def get_whisper_model_factory() -> Callable[..., Any]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise AudioTranscriptionUnavailable("faster-whisper 패키지가 설치되어 있지 않습니다.") from error
    return WhisperModel


def set_whisper_model_factory_for_testing(factory: Callable[..., Any] | None) -> None:
    global _whisper_model_factory_override
    with _transcription_service_lock:
        _whisper_model_factory_override = factory
        reset_transcription_service_cache_for_testing()


def reset_transcription_service_cache_for_testing() -> None:
    global _transcription_service_cache
    _transcription_service_cache = None


_transcription_service_lock = Lock()
_transcription_service_cache: tuple[WhisperRuntimeConfig, FasterWhisperTranscriptionService] | None = None
_whisper_model_factory_override: Callable[..., Any] | None = None
