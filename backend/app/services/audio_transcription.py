"""Audio transcription service interface and optional WhisperX adapter."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import importlib.util
import math
import os
import re
from statistics import median
from threading import BoundedSemaphore, Lock
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
DURATION_LIMIT_ERROR = "음성 길이가 허용된 최대 처리 시간을 초과했습니다."
BUSY_ERROR = "다른 음성 축어록 작업이 진행 중입니다. 잠시 후 다시 시도해주세요."
ALIGNMENT_FALLBACK_WARNING = "한국어 단어 정렬에 실패해 ASR 구간 시간을 사용했습니다."
DIARIZATION_FALLBACK_WARNING = "화자 분리를 사용할 수 없어 단일 화자로 처리했습니다."
LANGUAGE_MISMATCH_WARNING = "인식된 언어가 한국어 설정과 일치하지 않아 결과를 검토해야 합니다."
WHISPERX_SAMPLE_RATE = 16_000

AudioRuntimeMode = Literal["disabled", "stub", "real"]
DiarizationStatus = Literal["completed", "fallback", "disabled"]
AlignmentStatus = Literal["completed", "fallback", "disabled"]


@dataclass(frozen=True)
class WhisperXRuntimeConfig:
    model_name: str
    language: str
    device: str
    compute_type: str
    batch_size: int
    align_model_name: str
    diarization_enabled: bool
    diarization_model_name: str
    max_duration_seconds: float
    max_concurrent_jobs: int


@dataclass(frozen=True)
class TranscriptionServiceCacheKey:
    runtime_mode: AudioRuntimeMode
    engine: str
    whisperx: WhisperXRuntimeConfig | None = None


@dataclass(frozen=True)
class AsrModelCacheKey:
    model_name: str
    device: str
    compute_type: str
    language: str


@dataclass(frozen=True)
class AlignmentModelCacheKey:
    language: str
    model_name: str
    device: str


@dataclass(frozen=True)
class DiarizationModelCacheKey:
    model_name: str
    device: str


@dataclass(frozen=True)
class WhisperXRuntime:
    whisperx: Any
    diarization_pipeline_factory: Callable[..., Any]
    torch: Any
    sample_rate: int = WHISPERX_SAMPLE_RATE


@dataclass(frozen=True)
class _NormalizedWord:
    start: float
    end: float
    text: str
    speaker: str
    probability: float | None
    order: int


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
    """Deterministic demo transcription that never imports real audio runtimes."""

    def transcribe(
        self,
        upload: ValidatedUpload,
        *,
        language: str | None = None,
        task: str = "transcribe",
        expected_speakers: int = 2,
    ) -> AudioTranscriptionResponse:
        speaker_count = max(1, min(expected_speakers, 4))
        segments = [
            AudioSegment(
                id=1,
                start=0.0,
                end=4.2,
                text="지난주 발표 이후 계속 망했다는 생각이 들었어요.",
                speaker="speaker_1",
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
                speaker=f"speaker_{min(2, speaker_count)}",
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
                speaker=f"speaker_{min(3, speaker_count)}",
                pause_before_seconds=0.9,
                duration_seconds=4.4,
                speech_rate_wps=1.5,
                speech_rate_level="slow",
                volume_level="low",
                confidence=0.9,
            ),
        ]
        transcript_text = "\n".join(segment.text for segment in segments)
        return AudioTranscriptionResponse(
            transcription_id=f"transcription_{uuid4().hex}",
            filename=upload.filename,
            runtime_mode="stub",
            transcription_engine="stub",
            alignment_status="disabled",
            diarization_status="fallback",
            duration_seconds=13.8,
            language=language or "ko",
            language_probability=0.99,
            segments=segments,
            transcript_text=transcript_text,
            nonverbal_notes="시연 예시: 낮은 음량, 긴 멈춤, 느린 말속도 후보가 포함됩니다.",
            warnings=[STUB_MODE_WARNING],
        )


class WhisperXTranscriptionService(AudioTranscriptionService):
    """Opt-in WhisperX adapter using public ASR, alignment, and diarization APIs."""

    def __init__(
        self,
        config: WhisperXRuntimeConfig | None = None,
        runtime: WhisperXRuntime | None = None,
    ) -> None:
        self.config = config or current_whisperx_config()
        self._runtime = runtime

    def transcribe(
        self,
        upload: ValidatedUpload,
        *,
        language: str | None = None,
        task: str = "transcribe",
        expected_speakers: int = 2,
    ) -> AudioTranscriptionResponse:
        try:
            with _audio_job_slot(self.config.max_concurrent_jobs):
                return self._transcribe(
                    upload,
                    language=language,
                    task=task,
                    expected_speakers=expected_speakers,
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

    def _transcribe(
        self,
        upload: ValidatedUpload,
        *,
        language: str | None,
        task: str,
        expected_speakers: int,
    ) -> AudioTranscriptionResponse:
        runtime = self._runtime or get_whisperx_runtime()
        device = _resolve_device(self.config.device, runtime.torch)
        compute_type = _resolve_compute_type(self.config.compute_type, device)
        audio = runtime.whisperx.load_audio(str(upload.temp_path))
        duration_seconds = _audio_duration_seconds(audio, runtime.sample_rate)
        if duration_seconds > self.config.max_duration_seconds:
            raise AudioDurationLimitError(DURATION_LIMIT_ERROR)

        asr_model = _get_asr_model(runtime, self.config, device, compute_type)
        asr_result = asr_model.transcribe(
            audio,
            batch_size=self.config.batch_size,
            language=self.config.language,
            task=task,
        )
        asr_segments = _result_segments(asr_result)
        if not asr_segments:
            raise AudioNoSpeechDetectedError(NO_SPEECH_ERROR)

        warnings: list[str] = []
        detected_language = str(_mapping_value(asr_result, "language") or self.config.language)
        requested_language = (language or self.config.language).lower()
        if detected_language.lower() != self.config.language.lower() or requested_language != self.config.language.lower():
            warnings.append(LANGUAGE_MISMATCH_WARNING)

        aligned_result, alignment_status = self._align(runtime, audio, asr_result, device, warnings)
        final_result, diarization_status = self._assign_speakers(
            runtime,
            audio,
            aligned_result,
            device,
            expected_speakers,
            warnings,
        )
        force_speaker = "SPEAKER_00" if diarization_status == "fallback" else None
        segments = _normalize_whisperx_turns(final_result, force_speaker=force_speaker)
        if not segments:
            raise AudioNoSpeechDetectedError(NO_SPEECH_ERROR)
        segments = _apply_deterministic_audio_features(segments, audio, runtime.sample_rate)
        transcript_text = "\n".join(segment.text for segment in segments).strip()
        if not transcript_text:
            raise AudioNoSpeechDetectedError(NO_SPEECH_ERROR)

        return AudioTranscriptionResponse(
            transcription_id=f"transcription_{uuid4().hex}",
            filename=upload.filename,
            runtime_mode="real",
            transcription_engine="whisperx",
            alignment_model=self.config.align_model_name,
            diarization_model=(
                self.config.diarization_model_name if self.config.diarization_enabled else None
            ),
            alignment_status=alignment_status,
            diarization_status=diarization_status,
            duration_seconds=round(duration_seconds, 3),
            language=detected_language,
            language_probability=_safe_float(_mapping_value(asr_result, "language_probability")),
            segments=segments,
            transcript_text=transcript_text,
            warnings=warnings,
        )

    def _align(
        self,
        runtime: WhisperXRuntime,
        audio: Any,
        asr_result: Any,
        device: str,
        warnings: list[str],
    ) -> tuple[Any, AlignmentStatus]:
        try:
            align_model, align_metadata = _get_alignment_model(runtime, self.config, device)
            aligned_result = runtime.whisperx.align(
                _result_segments(asr_result),
                align_model,
                align_metadata,
                audio,
                device,
                return_char_alignments=False,
            )
            if not _result_segments(aligned_result):
                raise ValueError("empty alignment result")
            return aligned_result, "completed"
        except Exception:
            warnings.append(ALIGNMENT_FALLBACK_WARNING)
            return _copy_transcription_result(asr_result), "fallback"

    def _assign_speakers(
        self,
        runtime: WhisperXRuntime,
        audio: Any,
        aligned_result: Any,
        device: str,
        expected_speakers: int,
        warnings: list[str],
    ) -> tuple[Any, DiarizationStatus]:
        if not self.config.diarization_enabled:
            return aligned_result, "disabled"
        token = os.getenv("HF_TOKEN", "").strip()
        if not token:
            warnings.append(DIARIZATION_FALLBACK_WARNING)
            return aligned_result, "fallback"
        try:
            pipeline = _get_diarization_pipeline(runtime, self.config, device, token)
            diarization_result = pipeline(
                audio,
                num_speakers=max(1, min(expected_speakers, 4)),
            )
            assigned_result = runtime.whisperx.assign_word_speakers(
                diarization_result,
                aligned_result,
            )
            if not _result_segments(assigned_result):
                raise ValueError("empty speaker assignment result")
            return assigned_result, "completed"
        except Exception:
            warnings.append(DIARIZATION_FALLBACK_WARNING)
            return aligned_result, "fallback"


def get_audio_capabilities() -> AudioCapabilitiesResponse:
    runtime_mode = get_audio_runtime_mode()
    transcription = get_transcription_capability()
    config = current_whisperx_config()
    token_configured = bool(os.getenv("HF_TOKEN", "").strip())
    diarization_available = runtime_mode == "stub" or (
        runtime_mode == "real"
        and transcription.available
        and config.diarization_enabled
        and token_configured
    )
    diarization_reason = None
    if not diarization_available:
        if runtime_mode == "real" and config.diarization_enabled and not token_configured:
            diarization_reason = "화자 분리 토큰이 없어 단일 화자 fallback으로 처리됩니다."
        else:
            diarization_reason = "실제 화자 분리는 WhisperX 런타임에서 별도 설정 후 활성화됩니다."
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
    engine = current_audio_engine()
    if runtime_mode == "disabled":
        capability = get_transcription_capability()
        return UnavailableAudioTranscriptionService(capability.reason or UNAVAILABLE_REASON)

    cache_key = TranscriptionServiceCacheKey(
        runtime_mode=runtime_mode,
        engine="stub" if runtime_mode == "stub" else engine,
        whisperx=current_whisperx_config() if runtime_mode == "real" else None,
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
            service = WhisperXTranscriptionService(
                config=cache_key.whisperx,
                runtime=_whisperx_runtime_override,
            )
        _transcription_service_cache = (cache_key, service)
        return service


def get_audio_runtime_mode() -> AudioRuntimeMode:
    if os.getenv("AUDIO_TRANSCRIPTION_STUB", "0") == "1":
        return "stub"
    if os.getenv("AUDIO_TRANSCRIPTION_STUB", "0") == "0" and os.getenv("ENABLE_AUDIO_TRANSCRIPTION", "0") == "1":
        return "real"
    return "disabled"


def current_audio_engine() -> str:
    return (os.getenv("AUDIO_TRANSCRIPTION_ENGINE", "whisperx").strip() or "whisperx").lower()


def get_transcription_capability() -> AudioCapability:
    runtime_mode = get_audio_runtime_mode()
    if runtime_mode == "stub":
        return AudioCapability(available=True)
    if runtime_mode == "disabled":
        return AudioCapability(available=False, reason=UNAVAILABLE_REASON)
    if current_audio_engine() != "whisperx":
        return AudioCapability(available=False, reason="지원하지 않는 음성 축어록 엔진 설정입니다.")
    if _whisperx_runtime_override is not None:
        return AudioCapability(available=True)
    if importlib.util.find_spec("whisperx") is None:
        return AudioCapability(available=False, reason="WhisperX 패키지가 설치되어 있지 않습니다.")
    return AudioCapability(available=True)


def current_whisperx_config() -> WhisperXRuntimeConfig:
    return WhisperXRuntimeConfig(
        model_name=os.getenv("WHISPERX_MODEL", "large-v3").strip() or "large-v3",
        language=(os.getenv("WHISPERX_LANGUAGE", "ko").strip() or "ko").lower(),
        device=(os.getenv("WHISPERX_DEVICE", "auto").strip() or "auto").lower(),
        compute_type=(os.getenv("WHISPERX_COMPUTE_TYPE", "float16").strip() or "float16").lower(),
        batch_size=_positive_int_env("WHISPERX_BATCH_SIZE", 4),
        align_model_name=(
            os.getenv("WHISPERX_ALIGN_MODEL", "kresnik/wav2vec2-large-xlsr-korean").strip()
            or "kresnik/wav2vec2-large-xlsr-korean"
        ),
        diarization_enabled=os.getenv("ENABLE_AUDIO_DIARIZATION", "0") == "1",
        diarization_model_name=(
            os.getenv(
                "WHISPERX_DIARIZATION_MODEL",
                "pyannote/speaker-diarization-community-1",
            ).strip()
            or "pyannote/speaker-diarization-community-1"
        ),
        max_duration_seconds=_positive_float_env("AUDIO_MAX_DURATION_SECONDS", 7200.0),
        max_concurrent_jobs=_positive_int_env("AUDIO_MAX_CONCURRENT_JOBS", 1),
    )


def get_whisperx_runtime() -> WhisperXRuntime:
    if _whisperx_runtime_override is not None:
        return _whisperx_runtime_override
    try:
        import torch
        import whisperx
    except ImportError as error:
        raise AudioTranscriptionUnavailable("WhisperX 패키지가 설치되어 있지 않습니다.") from error

    def diarization_pipeline_factory(**kwargs: Any) -> Any:
        from whisperx.diarize import DiarizationPipeline

        return DiarizationPipeline(**kwargs)

    return WhisperXRuntime(
        whisperx=whisperx,
        diarization_pipeline_factory=diarization_pipeline_factory,
        torch=torch,
    )


def set_whisperx_runtime_for_testing(runtime: WhisperXRuntime | None) -> None:
    global _whisperx_runtime_override, _transcription_service_cache
    with _transcription_service_lock:
        _whisperx_runtime_override = runtime
        _transcription_service_cache = None
    reset_whisperx_model_caches_for_testing()


def reset_transcription_service_cache_for_testing() -> None:
    global _transcription_service_cache
    _transcription_service_cache = None


def reset_whisperx_model_caches_for_testing() -> None:
    with _model_initialization_lock:
        _asr_model_cache.clear()
        _alignment_model_cache.clear()
        _diarization_pipeline_cache.clear()
    with _job_semaphore_lock:
        _job_semaphores.clear()


def _get_asr_model(
    runtime: WhisperXRuntime,
    config: WhisperXRuntimeConfig,
    device: str,
    compute_type: str,
) -> Any:
    key = AsrModelCacheKey(
        model_name=config.model_name,
        device=device,
        compute_type=compute_type,
        language=config.language,
    )
    with _model_initialization_lock:
        if key not in _asr_model_cache:
            _asr_model_cache[key] = runtime.whisperx.load_model(
                config.model_name,
                device,
                compute_type=compute_type,
                language=config.language,
                task="transcribe",
            )
        return _asr_model_cache[key]


def _get_alignment_model(
    runtime: WhisperXRuntime,
    config: WhisperXRuntimeConfig,
    device: str,
) -> tuple[Any, Any]:
    key = AlignmentModelCacheKey(
        language=config.language,
        model_name=config.align_model_name,
        device=device,
    )
    with _model_initialization_lock:
        if key not in _alignment_model_cache:
            _alignment_model_cache[key] = runtime.whisperx.load_align_model(
                language_code=config.language,
                device=device,
                model_name=config.align_model_name,
            )
        return _alignment_model_cache[key]


def _get_diarization_pipeline(
    runtime: WhisperXRuntime,
    config: WhisperXRuntimeConfig,
    device: str,
    token: str,
) -> Any:
    key = DiarizationModelCacheKey(
        model_name=config.diarization_model_name,
        device=device,
    )
    with _model_initialization_lock:
        if key not in _diarization_pipeline_cache:
            _diarization_pipeline_cache[key] = runtime.diarization_pipeline_factory(
                model_name=config.diarization_model_name,
                token=token,
                device=device,
            )
        return _diarization_pipeline_cache[key]


def _normalize_whisperx_turns(
    result: Any,
    *,
    force_speaker: str | None = None,
) -> list[AudioSegment]:
    words: list[_NormalizedWord] = []
    order = 0
    for segment in sorted(
        _result_segments(result),
        key=lambda item: _safe_float(_mapping_value(item, "start")) or 0.0,
    ):
        segment_start = max(0.0, _safe_float(_mapping_value(segment, "start")) or 0.0)
        segment_end = max(segment_start, _safe_float(_mapping_value(segment, "end")) or segment_start)
        segment_speaker = str(_mapping_value(segment, "speaker") or "SPEAKER_00")
        segment_words = _mapping_value(segment, "words") or []
        added_word = False
        for word in segment_words:
            text = str(_mapping_value(word, "word") or _mapping_value(word, "text") or "").strip()
            if not text:
                continue
            start = _safe_float(_mapping_value(word, "start"))
            end = _safe_float(_mapping_value(word, "end"))
            start = segment_start if start is None else max(0.0, start)
            end = segment_end if end is None else max(start, end)
            speaker = force_speaker or str(_mapping_value(word, "speaker") or segment_speaker)
            probability = _safe_probability(
                _mapping_value(word, "score")
                if _mapping_value(word, "score") is not None
                else _mapping_value(word, "probability")
            )
            words.append(
                _NormalizedWord(
                    start=start,
                    end=end,
                    text=text,
                    speaker=speaker,
                    probability=probability,
                    order=order,
                )
            )
            order += 1
            added_word = True
        if added_word:
            continue
        text = str(_mapping_value(segment, "text") or "").strip()
        if not text:
            continue
        words.append(
            _NormalizedWord(
                start=segment_start,
                end=segment_end,
                text=text,
                speaker=force_speaker or segment_speaker,
                probability=_safe_probability(_mapping_value(segment, "score")),
                order=order,
            )
        )
        order += 1

    words.sort(key=lambda item: (item.start, item.end, item.order))
    turns: list[AudioSegment] = []
    current: list[_NormalizedWord] = []
    current_speaker: str | None = None
    current_end = 0.0
    for word in words:
        starts_new_turn = bool(
            current
            and (
                word.speaker != current_speaker
                or word.start - current_end > 1.0
            )
        )
        if starts_new_turn:
            turns.append(_build_audio_turn(len(turns) + 1, current))
            current = []
        current.append(word)
        current_speaker = word.speaker
        current_end = max(current_end if len(current) > 1 else word.end, word.end)
    if current:
        turns.append(_build_audio_turn(len(turns) + 1, current))
    return turns


def _build_audio_turn(turn_id: int, words: list[_NormalizedWord]) -> AudioSegment:
    start = min(word.start for word in words)
    end = max(word.end for word in words)
    probabilities = [word.probability for word in words if word.probability is not None]
    return AudioSegment(
        id=turn_id,
        start=start,
        end=end,
        text=_join_word_texts([word.text for word in words]),
        speaker=words[0].speaker,
        confidence=(round(sum(probabilities) / len(probabilities), 4) if probabilities else None),
        words=[
            AudioWord(
                start=word.start,
                end=word.end,
                text=word.text,
                speaker=word.speaker,
                probability=word.probability,
            )
            for word in words
        ],
    )


def _apply_deterministic_audio_features(
    segments: list[AudioSegment],
    audio: Any,
    sample_rate: int,
) -> list[AudioSegment]:
    ordered = sorted(segments, key=lambda segment: (segment.start, segment.end, segment.id))
    previous_end = 0.0
    enriched: list[AudioSegment] = []
    rms_by_id: dict[int, float] = {}
    for index, segment in enumerate(ordered, start=1):
        duration = max(0.0, segment.end - segment.start)
        pause = max(0.0, segment.start - previous_end)
        rate = _speech_rate_wps(segment.text, duration)
        rms = _turn_rms(audio, segment.start, segment.end, sample_rate)
        if rms is not None:
            rms_by_id[index] = rms
        enriched.append(
            segment.model_copy(
                update={
                    "id": index,
                    "pause_before_seconds": round(pause, 3),
                    "duration_seconds": round(duration, 3),
                    "speech_rate_wps": rate,
                    "speech_rate_level": None,
                    "volume_level": None,
                }
            )
        )
        previous_end = max(previous_end, segment.end)
    enriched = _apply_relative_speech_rate_levels(enriched)
    return _apply_relative_volume_levels(enriched, rms_by_id)


def _apply_relative_speech_rate_levels(segments: list[AudioSegment]) -> list[AudioSegment]:
    grouped: dict[str, list[float]] = {}
    for segment in segments:
        if segment.speech_rate_wps is not None:
            grouped.setdefault(segment.speaker or "SPEAKER_00", []).append(segment.speech_rate_wps)
    baselines = {
        speaker: median(rates)
        for speaker, rates in grouped.items()
        if len(rates) >= 3
    }
    updated: list[AudioSegment] = []
    for segment in segments:
        baseline = baselines.get(segment.speaker or "SPEAKER_00")
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


def _apply_relative_volume_levels(
    segments: list[AudioSegment],
    rms_by_id: dict[int, float],
) -> list[AudioSegment]:
    grouped: dict[str, list[float]] = {}
    db_by_id: dict[int, float] = {}
    for segment in segments:
        rms = rms_by_id.get(segment.id)
        if rms is None or rms <= 0:
            continue
        db = 20.0 * math.log10(rms)
        db_by_id[segment.id] = db
        grouped.setdefault(segment.speaker or "SPEAKER_00", []).append(db)

    thresholds: dict[str, tuple[float, float]] = {}
    for speaker, values in grouped.items():
        if len(values) < 3:
            continue
        center = median(values)
        mad = median([abs(value - center) for value in values])
        margin = max(3.0, mad)
        thresholds[speaker] = (center - margin, center + margin)

    updated: list[AudioSegment] = []
    for segment in segments:
        bounds = thresholds.get(segment.speaker or "SPEAKER_00")
        db = db_by_id.get(segment.id)
        level: Literal["low", "typical", "high"] | None = None
        if bounds is not None and db is not None:
            if db <= bounds[0]:
                level = "low"
            elif db >= bounds[1]:
                level = "high"
            else:
                level = "typical"
        updated.append(segment.model_copy(update={"volume_level": level}))
    return updated


def _turn_rms(audio: Any, start: float, end: float, sample_rate: int) -> float | None:
    start_index = max(0, int(start * sample_rate))
    end_index = max(start_index, int(end * sample_rate))
    if end_index <= start_index:
        return None
    samples = audio[start_index:end_index]
    try:
        if len(samples) == 0:
            return None
        values = samples.astype("float64", copy=False)
        mean_square = float((values * values).mean())
    except (AttributeError, TypeError, ValueError):
        values = [float(value) for value in samples]
        if not values:
            return None
        mean_square = sum(value * value for value in values) / len(values)
    if not math.isfinite(mean_square) or mean_square < 0:
        return None
    return math.sqrt(mean_square)


def _resolve_device(configured_device: str, torch_module: Any) -> str:
    if configured_device != "auto":
        return configured_device
    try:
        return "cuda" if torch_module.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _resolve_compute_type(configured_compute_type: str, device: str) -> str:
    if configured_compute_type in {"auto", "default"}:
        return "float16" if device == "cuda" else "int8"
    if device == "cpu" and configured_compute_type == "float16":
        return "int8"
    return configured_compute_type


def _audio_duration_seconds(audio: Any, sample_rate: int) -> float:
    if sample_rate <= 0:
        return 0.0
    shape = getattr(audio, "shape", None)
    sample_count = int(shape[-1]) if shape else len(audio)
    return max(0.0, sample_count / sample_rate)


@contextmanager
def _audio_job_slot(max_concurrent_jobs: int) -> Iterator[None]:
    semaphore = _get_audio_job_semaphore(max_concurrent_jobs)
    if not semaphore.acquire(blocking=False):
        raise AudioTranscriptionBusyError(BUSY_ERROR)
    try:
        yield
    finally:
        semaphore.release()


def _get_audio_job_semaphore(max_concurrent_jobs: int) -> BoundedSemaphore:
    with _job_semaphore_lock:
        if max_concurrent_jobs not in _job_semaphores:
            _job_semaphores[max_concurrent_jobs] = BoundedSemaphore(max_concurrent_jobs)
        return _job_semaphores[max_concurrent_jobs]


def _result_segments(result: Any) -> list[Any]:
    segments = _mapping_value(result, "segments")
    return list(segments or [])


def _copy_transcription_result(result: Any) -> dict[str, Any]:
    copied = {"segments": _result_segments(result)}
    language = _mapping_value(result, "language")
    if language is not None:
        copied["language"] = language
    return copied


def _mapping_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _join_word_texts(words: list[str]) -> str:
    text = " ".join(word.strip() for word in words if word.strip())
    return re.sub(r"\s+([,.;:!?…])", r"\1", text).strip()


def _speech_rate_wps(text: str, duration_seconds: float) -> float | None:
    if duration_seconds <= 0:
        return None
    words = [part for part in text.replace("\n", " ").split(" ") if part.strip()]
    count = len(words) if words else max(1, len(text.replace(" ", "")) // 3)
    return round(count / duration_seconds, 2)


def _safe_probability(value: Any) -> float | None:
    number = _safe_float(value)
    if number is None:
        return None
    return min(1.0, max(0.0, number))


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive_int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _positive_float_env(name: str, default: float) -> float:
    try:
        return max(1.0, float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


_transcription_service_lock = Lock()
_transcription_service_cache: tuple[TranscriptionServiceCacheKey, AudioTranscriptionService] | None = None
_whisperx_runtime_override: WhisperXRuntime | None = None

_model_initialization_lock = Lock()
_asr_model_cache: dict[AsrModelCacheKey, Any] = {}
_alignment_model_cache: dict[AlignmentModelCacheKey, tuple[Any, Any]] = {}
_diarization_pipeline_cache: dict[DiarizationModelCacheKey, Any] = {}

_job_semaphore_lock = Lock()
_job_semaphores: dict[int, BoundedSemaphore] = {}
