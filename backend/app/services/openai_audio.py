"""Bounded hosted transcription. Audio is never retained by this application.

Provider retention follows the configured OpenAI account policy. Speaker references
are supplied by the browser for this request only; no provider URLs are accepted.
"""
from __future__ import annotations

import base64
import io
import math
import os
import re
import time
import wave
from uuid import uuid4

from app.schemas.audio import AudioSegment, AudioTranscriptionResponse
from app.services.audio_transcription import (
    AudioDurationLimitError, AudioNoSpeechDetectedError, AudioTranscriptionRuntimeError,
    AudioTranscriptionUnavailable,
)
from app.services.upload_validation import UploadValidationError, ValidatedUpload

MODEL = "gpt-4o-transcribe-diarize"
MAX_CHUNK_BYTES = 2_000_000


def wav_duration(source) -> float:
    try:
        with wave.open(source, "rb") as audio:
            if audio.getnchannels() != 1 or audio.getsampwidth() != 2 or audio.getframerate() != 16000:
                raise ValueError("Unsupported PCM format")
            frames = audio.getnframes()
            if len(audio.readframes(frames)) != frames * 2:
                raise ValueError("Truncated PCM")
            return frames / 16000
    except (wave.Error, EOFError, ValueError) as error:
        raise UploadValidationError(422, "음성을 16kHz 모노 WAV로 변환한 뒤 다시 시도해주세요.") from error


def validate_references(references: list[dict]) -> tuple[list[str], list[str]]:
    if not isinstance(references, list) or len(references) > 4:
        raise UploadValidationError(422, "화자 참조는 최대 4개입니다.")
    names, clips = [], []
    for ref in references:
        if not isinstance(ref, dict):
            raise UploadValidationError(422, "화자 참조 형식이 올바르지 않습니다.")
        name, clip = ref.get("name", ""), ref.get("audio", "")
        if not isinstance(name, str) or not re.fullmatch(r"speaker_[0-3]", name) or name in names:
            raise UploadValidationError(422, "화자 참조 이름이 올바르지 않습니다.")
        prefix = "data:audio/wav;base64,"
        if not isinstance(clip, str) or len(clip) > 175_000 or not clip.startswith(prefix):
            raise UploadValidationError(422, "화자 참조 오디오가 올바르지 않습니다.")
        try:
            data = base64.b64decode(clip[len(prefix):], validate=True)
        except ValueError as error:
            raise UploadValidationError(422, "화자 참조 오디오가 올바르지 않습니다.") from error
        if not 2 <= wav_duration(io.BytesIO(data)) <= 4:
            raise UploadValidationError(422, "화자 참조는 2~4초여야 합니다.")
        names.append(name)
        clips.append(clip)
    return names, clips


class OpenAIAudioTranscriptionService:
    def transcribe(self, upload: ValidatedUpload, *, language=None, task="transcribe",
                   expected_speakers=2, speaker_references=None) -> AudioTranscriptionResponse:
        if not os.getenv("OPENAI_API_KEY"):
            raise AudioTranscriptionUnavailable("음성 API 연결 설정이 필요합니다.")
        if upload.suffix != ".wav" or upload.size_bytes > MAX_CHUNK_BYTES:
            raise UploadValidationError(413, "음성을 60초 이하 WAV 구간으로 나누어 업로드해주세요.")
        duration = wav_duration(str(upload.temp_path))
        if duration <= 0 or duration > 60:
            raise AudioDurationLimitError("음성 구간은 60초 이하여야 합니다.")
        names, clips = validate_references(speaker_references or [])
        started = time.perf_counter()
        model = os.getenv("OPENAI_AUDIO_MODEL", MODEL)
        if model != MODEL:
            raise AudioTranscriptionUnavailable("화자분리를 지원하는 음성 모델 설정을 확인해주세요.")
        from openai import OpenAI, APIError
        try:
            # Do not inherit a local summary model's OPENAI_BASE_URL.
            with OpenAI(api_key=os.environ["OPENAI_API_KEY"], base_url="https://api.openai.com/v1",
                        timeout=180, max_retries=0) as client, upload.temp_path.open("rb") as audio:
                result = client.audio.transcriptions.create(
                    model=model, file=("chunk.wav", audio, "audio/wav"), language="ko",
                    response_format="diarized_json", chunking_strategy="auto",
                    extra_body={"known_speaker_names": names, "known_speaker_references": clips} if names else {},
                )
            payload = result.model_dump() if hasattr(result, "model_dump") else result
        except APIError as error:
            # Never return provider bodies, filenames, transcripts or credentials.
            code = getattr(error, "status_code", None)
            message = ("음성 API 사용량 또는 요청 한도를 초과했습니다. 잠시 후 다시 시도해주세요."
                       if code == 429 else "음성 API 처리에 실패했습니다. 연결 및 모델 설정을 확인해주세요.")
            raise AudioTranscriptionRuntimeError(message) from error
        segments = []
        for index, item in enumerate(payload.get("segments") or []):
            start, end = item.get("start"), item.get("end")
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or not (
                math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= duration + 1
            ):
                raise AudioTranscriptionRuntimeError("음성 구간의 시간 정보가 올바르지 않습니다. 다시 시도해주세요.")
            speaker = item.get("speaker")
            segments.append(AudioSegment(id=index, segment_id=f"seg_{index}", start=start,
                end=min(end, duration), text=text, speaker=str(speaker) if speaker is not None else None,
                review_flags=[] if speaker is not None else ["speaker_unassigned"]))
        fallback = False
        if not segments:
            text = str(payload.get("text") or "").strip()
            if not text:
                raise AudioNoSpeechDetectedError("음성에서 발화를 찾지 못했습니다.")
            fallback = True
            segments = [AudioSegment(id=0, segment_id="seg_0", start=0, end=duration,
                text=text, review_flags=["speaker_unassigned", "timestamp_unavailable"])]
        segments.sort(key=lambda s: (s.start, s.end))
        return AudioTranscriptionResponse(transcription_id=f"transcription_{uuid4().hex}",
            filename=upload.filename, runtime_mode="real", transcription_engine="openai",
            diarization_model=model, diarization_status="fallback" if fallback else "completed",
            duration_seconds=duration, language="ko", segments=segments,
            raw_segments=[s.model_copy(deep=True) for s in segments],
            transcript_text="\n".join(s.text for s in segments),
            warnings=["자동 화자 및 숫자·부정·고유명사를 원음과 대조해주세요."],
            error_codes=["diarization_failed"] if fallback else [],
            stage_metrics={"total_seconds": time.perf_counter() - started})
