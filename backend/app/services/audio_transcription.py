"""Audio transcription service interface and optional faster-whisper adapter."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
import os
from threading import Lock
from typing import Any, Literal
from uuid import uuid4

from app.schemas.audio import (
    AudioCapabilitiesResponse,
    AudioCapability,
    AudioSegment,
    AudioTranscriptionResponse,
    AudioWord,
)
from app.services.upload_validation import ValidatedUpload


UNAVAILABLE_REASON = (
    "음성 자동 축어록 런타임이 비활성화되어 있습니다. "
    "시연 모드는 AUDIO_TRANSCRIPTION_STUB=1, 실제 STT는 ENABLE_AUDIO_TRANSCRIPTION=1 및 "
    "AUDIO_TRANSCRIPTION_STUB=0으로 설정해야 합니다."
)
STUB_MODE_WARNING = "시연용 예시 축어록이며 업로드 음성을 분석한 결과가 아닙니다."
SAFE_RUNTIME_ERROR = "음성 축어록 생성 중 오류가 발생했습니다."
NO_SPEECH_ERROR = "음성에서 인식 가능한 발화를 찾지 못했습니다."

AudioRuntimeMode = Literal["disabled", "stub", "real"]
DiarizationStatus = Literal["completed", "fallback", "disabled"]


@dataclass(frozen=True)
class WhisperRuntimeConfig:
    model_size: str
    device: str
    compute_type: str


@dataclass(frozen=True)
class TranscriptionServiceCacheKey:
    runtime_mode: AudioRuntimeMode
    whisper: WhisperRuntimeConfig | None = None
    diarization_enabled: bool = False


@dataclass(frozen=True)
class DiarizationRuntimeConfig:
    enabled: bool
    model_name: str
    auth_token: str | None


@dataclass(frozen=True)
class AudioDiarizationResult:
    segments: list[AudioSegment]
    status: DiarizationStatus
    warnings: list[str]


class AudioNoSpeechDetectedError(Exception):
    """Raised when the runtime returns no usable transcript text."""


class AudioDurationLimitError(Exception):
    """Raised when the requested audio exceeds runtime duration limits."""


class AudioTranscriptionBusyError(Exception):
    """Raised when the transcription backend is saturated."""


class AudioTranscriptionUnavailable(Exception):
    """Raised when transcription is not configured on this runtime."""

    def __init__(self, reason: str = UNAVAILABLE_REASON) -> None:
        super().__init__(reason)
        self.reason = reason


class AudioTranscriptionRuntimeError(Exception):
    """Raised when an enabled transcription runtime fails safely."""


class AudioDiarizationService(ABC):
    """Optional speaker diarization extension point."""

    @abstractmethod
    def assign_speakers(
        self,
        segments: list[AudioSegment],
        *,
        audio_path: str,
        num_speakers: int,
    ) -> AudioDiarizationResult:
        """Return segments with speaker ids or leave them unchanged."""


class DisabledDiarizationService(AudioDiarizationService):
    def assign_speakers(
        self,
        segments: list[AudioSegment],
        *,
        audio_path: str,
        num_speakers: int,
    ) -> AudioDiarizationResult:
        return AudioDiarizationResult(segments=segments, status="disabled", warnings=[])


class FallbackDiarizationService(AudioDiarizationService):
    def __init__(self, warning: str = "화자 분리를 사용할 수 없어 단일 화자로 처리했습니다.") -> None:
        self.warning = warning

    def assign_speakers(
        self,
        segments: list[AudioSegment],
        *,
        audio_path: str,
        num_speakers: int,
    ) -> AudioDiarizationResult:
        return AudioDiarizationResult(
            segments=[segment.model_copy(update={"speaker": "speaker_1"}) for segment in segments],
            status="fallback",
            warnings=[self.warning],
        )


class StubDiarizationService(AudioDiarizationService):
    def assign_speakers(
        self,
        segments: list[AudioSegment],
        *,
        audio_path: str,
        num_speakers: int,
    ) -> AudioDiarizationResult:
        speaker_count = max(1, min(num_speakers, 4))
        assigned = [
            segment.model_copy(update={"speaker": f"speaker_{((index - 1) % speaker_count) + 1}"})
            for index, segment in enumerate(segments, start=1)
        ]
        return AudioDiarizationResult(segments=assigned, status="fallback", warnings=[])


class PyannoteDiarizationService(AudioDiarizationService):
    """Optional pyannote adapter. Any setup or inference failure falls back safely."""

    def __init__(
        self,
        config: DiarizationRuntimeConfig | None = None,
        fallback: AudioDiarizationService | None = None,
    ) -> None:
        self.config = config or current_diarization_config()
        self._fallback = fallback or FallbackDiarizationService()
        self._pipeline = None
        self._pipeline_lock = Lock()

    def assign_speakers(
        self,
        segments: list[AudioSegment],
        *,
        audio_path: str,
        num_speakers: int,
    ) -> AudioDiarizationResult:
        try:
            pipeline = self._get_pipeline()
            diarization = pipeline(audio_path, num_speakers=max(1, min(num_speakers, 4)))
            assigned = _assign_speaker_labels_from_diarization(segments, diarization)
            if not assigned:
                return self._fallback.assign_speakers(
                    segments,
                    audio_path=audio_path,
                    num_speakers=num_speakers,
                )
            return AudioDiarizationResult(segments=assigned, status="completed", warnings=[])
        except Exception:
            return self._fallback.assign_speakers(
                segments,
                audio_path=audio_path,
                num_speakers=num_speakers,
            )

    def _get_pipeline(self):
        if self._pipeline is not None:
            return self._pipeline
        with self._pipeline_lock:
            if self._pipeline is None:
                if not self.config.auth_token:
                    raise AudioTranscriptionUnavailable("화자 분리 토큰이 설정되어 있지 않습니다.")
                try:
                    from pyannote.audio import Pipeline
                except ImportError as error:
                    raise AudioTranscriptionUnavailable("화자 분리 런타임이 설치되어 있지 않습니다.") from error
                self._pipeline = Pipeline.from_pretrained(
                    self.config.model_name,
                    use_auth_token=self.config.auth_token,
                )
        return self._pipeline


class AudioTranscriptionService(ABC):
    """Interface for audio transcription implementations."""

    @abstractmethod
    def transcribe(
        self,
        upload: ValidatedUpload,
        *,
        language: str | None = None,
        task: str = "transcribe",
        expected_speakers: int = 2,
    ) -> AudioTranscriptionResponse:
        """Return a transcription or raise a domain exception."""


class UnavailableAudioTranscriptionService(AudioTranscriptionService):
    def __init__(self, reason: str = UNAVAILABLE_REASON) -> None:
        self.reason = reason

    def transcribe(
        self,
        upload: ValidatedUpload,
        *,
        language: str | None = None,
        task: str = "transcribe",
        expected_speakers: int = 2,
    ) -> AudioTranscriptionResponse:
        raise AudioTranscriptionUnavailable(self.reason)


class StubAudioTranscriptionService(AudioTranscriptionService):
    """Deterministic demo transcription that never imports or calls real STT dependencies."""

    def __init__(self, diarization_service: AudioDiarizationService | None = None) -> None:
        self._diarization_service = diarization_service or StubDiarizationService()

    def transcribe(
        self,
        upload: ValidatedUpload,
        *,
        language: str | None = None,
        task: str = "transcribe",
        expected_speakers: int = 2,
    ) -> AudioTranscriptionResponse:
        segments = [
            AudioSegment(
                id=1,
                start=0.0,
                end=4.2,
                text="지난주 발표 이후 계속 망했다는 생각이 들었어요.",
                pause_before_seconds=0.0,
                duration_seconds=4.2,
                speech_rate_wps=1.9,
                speech_rate_level="typical",
                volume_level="low",
                confidence=0.92,
            ),
            AudioSegment(
                id=2,
                start=4.9,
                end=8.5,
                text="그 생각이 올라올 때 몸에서는 어떤 반응이 있었나요?",
                pause_before_seconds=0.7,
                duration_seconds=3.6,
                speech_rate_wps=1.7,
                speech_rate_level="typical",
                volume_level="typical",
                confidence=0.91,
            ),
            AudioSegment(
                id=3,
                start=9.4,
                end=13.8,
                text="목소리가 작아지고 시선을 피하게 됐던 것 같아요.",
                pause_before_seconds=0.9,
                duration_seconds=4.4,
                speech_rate_wps=1.5,
                speech_rate_level="slow",
                volume_level="low",
                confidence=0.9,
            ),
        ]
        diarization = self._diarization_service.assign_speakers(
            segments,
            audio_path=str(upload.temp_path),
            num_speakers=expected_speakers,
        )
        segments = diarization.segments
        transcript_text = "\n".join(segment.text for segment in segments)
        return AudioTranscriptionResponse(
            transcription_id=f"transcription_{uuid4().hex}",
            filename=upload.filename,
            runtime_mode="stub",
            diarization_status=diarization.status,
            duration_seconds=13.8,
            language=language or "ko",
            language_probability=0.99,
            segments=segments,
            transcript_text=transcript_text,
            nonverbal_notes="시연 예시: 낮은 음량, 긴 멈춤, 느린 말속도 후보가 포함됩니다.",
            warnings=[STUB_MODE_WARNING, *diarization.warnings],
        )


class FasterWhisperTranscriptionService(AudioTranscriptionService):
    """Opt-in faster-whisper adapter. Model download is never triggered unless enabled."""

    def __init__(
        self,
        config: WhisperRuntimeConfig | None = None,
        model_factory: Callable[..., Any] | None = None,
        diarization_service: AudioDiarizationService | None = None,
    ) -> None:
        self.config = config or current_whisper_config()
        self._model_factory = model_factory
        self._diarization_service = diarization_service or DisabledDiarizationService()
        self._model = None
        self._model_lock = Lock()

    def transcribe(
        self,
        upload: ValidatedUpload,
        *,
        language: str | None = None,
        task: str = "transcribe",
        expected_speakers: int = 2,
    ) -> AudioTranscriptionResponse:
        try:
            model = self._get_model()
            segments_iter, info = model.transcribe(
                str(upload.temp_path),
                language=language or None,
                task=task,
            )
            segments = _build_segments_from_whisper(segments_iter)
            diarization = self._diarization_service.assign_speakers(
                segments,
                audio_path=str(upload.temp_path),
                num_speakers=expected_speakers,
            )
            segments = _apply_relative_speech_rate_levels(diarization.segments)
            transcript_text = "\n".join(segment.text for segment in segments).strip()
            if not transcript_text:
                raise AudioNoSpeechDetectedError(NO_SPEECH_ERROR)
            duration_seconds = _resolve_duration_seconds(segments, info)
            return AudioTranscriptionResponse(
                transcription_id=f"transcription_{uuid4().hex}",
                filename=upload.filename,
                runtime_mode="real",
                diarization_status=diarization.status,
                duration_seconds=duration_seconds,
                language=getattr(info, "language", None) or language,
                language_probability=_safe_float(getattr(info, "language_probability", None)),
                segments=segments,
                transcript_text=transcript_text,
                warnings=diarization.warnings,
            )
        except (
            AudioDurationLimitError,
            AudioNoSpeechDetectedError,
            AudioTranscriptionBusyError,
            AudioTranscriptionUnavailable,
        ):
            raise
        except Exception as error:
            raise AudioTranscriptionRuntimeError(SAFE_RUNTIME_ERROR) from error

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
    runtime_mode = get_audio_runtime_mode()
    transcription = get_transcription_capability()
    diarization_config = current_diarization_config()
    diarization_available = runtime_mode == "stub" or (
        runtime_mode == "real" and diarization_config.enabled and bool(diarization_config.auth_token)
    )
    diarization_reason = None
    if not diarization_available:
        diarization_reason = (
            "화자 분리 토큰이 없어 단일 화자 fallback으로 처리됩니다."
            if runtime_mode == "real" and diarization_config.enabled
            else "실제 화자 분리는 H100 런타임에서 별도 pyannote 설정 후 활성화됩니다."
        )
    return AudioCapabilitiesResponse(
        upload=AudioCapability(available=True),
        transcription=transcription,
        speaker_diarization=AudioCapability(
            available=diarization_available,
            reason=diarization_reason,
        ),
        runtime_mode=runtime_mode,
    )


def get_transcription_service() -> AudioTranscriptionService:
    global _transcription_service_cache

    runtime_mode = get_audio_runtime_mode()
    if runtime_mode == "disabled":
        capability = get_transcription_capability()
        return UnavailableAudioTranscriptionService(capability.reason or UNAVAILABLE_REASON)

    cache_key = TranscriptionServiceCacheKey(
        runtime_mode=runtime_mode,
        whisper=current_whisper_config() if runtime_mode == "real" else None,
        diarization_enabled=current_diarization_config().enabled if runtime_mode == "real" else False,
    )
    with _transcription_service_lock:
        if _transcription_service_cache and _transcription_service_cache[0] == cache_key:
            return _transcription_service_cache[1]
        if runtime_mode == "stub":
            service: AudioTranscriptionService = StubAudioTranscriptionService()
        else:
            capability = get_transcription_capability()
            if not capability.available:
                return UnavailableAudioTranscriptionService(capability.reason or UNAVAILABLE_REASON)
            service = FasterWhisperTranscriptionService(
                config=cache_key.whisper,
                model_factory=_whisper_model_factory_override,
                diarization_service=get_diarization_service(),
            )
        _transcription_service_cache = (cache_key, service)
        return service


def get_audio_runtime_mode() -> AudioRuntimeMode:
    if os.getenv("AUDIO_TRANSCRIPTION_STUB", "0") == "1":
        return "stub"
    if os.getenv("AUDIO_TRANSCRIPTION_STUB", "0") == "0" and os.getenv("ENABLE_AUDIO_TRANSCRIPTION", "0") == "1":
        return "real"
    return "disabled"


def get_transcription_capability() -> AudioCapability:
    runtime_mode = get_audio_runtime_mode()
    if runtime_mode == "stub":
        return AudioCapability(available=True)
    if runtime_mode == "disabled":
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


def current_diarization_config() -> DiarizationRuntimeConfig:
    return DiarizationRuntimeConfig(
        enabled=os.getenv("ENABLE_AUDIO_DIARIZATION", "0") == "1",
        model_name=os.getenv("PYANNOTE_MODEL_NAME", "pyannote/speaker-diarization-3.1"),
        auth_token=os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN"),
    )


def get_diarization_service() -> AudioDiarizationService:
    config = current_diarization_config()
    if not config.enabled:
        return DisabledDiarizationService()
    return PyannoteDiarizationService(config=config)


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


def _build_segments_from_whisper(segments_iter: Any) -> list[AudioSegment]:
    segments: list[AudioSegment] = []
    previous_end = 0.0
    for index, segment in enumerate(segments_iter, start=1):
        text = str(getattr(segment, "text", "")).strip()
        if not text:
            continue
        start = max(0.0, float(getattr(segment, "start", 0.0) or 0.0))
        end = max(start, float(getattr(segment, "end", start) or start))
        duration = max(0.0, end - start)
        words = _extract_words(segment)
        speech_rate = _speech_rate_wps(text, duration)
        confidence = _segment_confidence(words)
        segments.append(
            AudioSegment(
                id=index,
                start=start,
                end=end,
                text=text,
                pause_before_seconds=max(0.0, start - previous_end),
                duration_seconds=duration,
                speech_rate_wps=speech_rate,
                confidence=confidence,
                words=words,
            )
        )
        previous_end = end
    return segments


def _extract_words(segment: Any) -> list[AudioWord]:
    words: list[AudioWord] = []
    for word in getattr(segment, "words", None) or []:
        text = str(getattr(word, "word", getattr(word, "text", ""))).strip()
        if not text:
            continue
        words.append(
            AudioWord(
                start=_safe_float(getattr(word, "start", None)),
                end=_safe_float(getattr(word, "end", None)),
                text=text,
                probability=_safe_float(getattr(word, "probability", None)),
            )
        )
    return words


def _resolve_duration_seconds(segments: list[AudioSegment], info: Any) -> float | None:
    duration = _safe_float(getattr(info, "duration", None))
    if duration is not None:
        return duration
    if segments:
        return max(segment.end for segment in segments)
    return None


def _apply_relative_speech_rate_levels(segments: list[AudioSegment]) -> list[AudioSegment]:
    grouped: dict[str, list[float]] = {}
    for segment in segments:
        if segment.speech_rate_wps is None:
            continue
        grouped.setdefault(segment.speaker or "__all__", []).append(segment.speech_rate_wps)

    baselines = {
        speaker: sorted(rates)[len(rates) // 2]
        for speaker, rates in grouped.items()
        if len(rates) >= 3
    }
    if not baselines:
        return [segment.model_copy(update={"speech_rate_level": None}) for segment in segments]

    updated: list[AudioSegment] = []
    for segment in segments:
        baseline = baselines.get(segment.speaker or "__all__")
        rate = segment.speech_rate_wps
        level: Literal["slow", "typical", "fast"] | None = None
        if baseline is not None and rate is not None and baseline > 0:
            if rate <= baseline * 0.75:
                level = "slow"
            elif rate >= baseline * 1.25:
                level = "fast"
            else:
                level = "typical"
        updated.append(segment.model_copy(update={"speech_rate_level": level}))
    return updated


def _assign_speaker_labels_from_diarization(segments: list[AudioSegment], diarization: Any) -> list[AudioSegment]:
    turns: list[tuple[float, float, str]] = []
    for turn, _track, label in diarization.itertracks(yield_label=True):
        start = _safe_float(getattr(turn, "start", None))
        end = _safe_float(getattr(turn, "end", None))
        if start is None or end is None or end <= start:
            continue
        turns.append((start, end, str(label)))
    if not turns:
        return []

    label_map: dict[str, str] = {}
    assigned: list[AudioSegment] = []
    for segment in segments:
        best_label = None
        best_overlap = 0.0
        for start, end, label in turns:
            overlap = max(0.0, min(segment.end, end) - max(segment.start, start))
            if overlap > best_overlap:
                best_overlap = overlap
                best_label = label
        if best_label is None:
            assigned.append(segment.model_copy(update={"speaker": "speaker_1"}))
            continue
        if best_label not in label_map:
            label_map[best_label] = f"speaker_{len(label_map) + 1}"
        assigned.append(segment.model_copy(update={"speaker": label_map[best_label]}))
    return assigned


def _speech_rate_wps(text: str, duration_seconds: float) -> float | None:
    if duration_seconds <= 0:
        return None
    words = [part for part in text.replace("\n", " ").split(" ") if part.strip()]
    count = len(words) if words else max(1, len(text.replace(" ", "")) // 3)
    return round(count / duration_seconds, 2)


def _segment_confidence(words: list[AudioWord]) -> float | None:
    probabilities = [word.probability for word in words if word.probability is not None]
    if not probabilities:
        return None
    return round(sum(probabilities) / len(probabilities), 4)


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


_transcription_service_lock = Lock()
_transcription_service_cache: tuple[TranscriptionServiceCacheKey, AudioTranscriptionService] | None = None
_whisper_model_factory_override: Callable[..., Any] | None = None
