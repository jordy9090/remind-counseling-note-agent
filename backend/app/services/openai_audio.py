"""Bounded hosted transcription. Audio is never retained by this application.

Provider retention follows the configured OpenAI account policy. Speaker references
are supplied by the browser for this request only; no provider URLs are accepted.
"""
from __future__ import annotations

import math
import os
import time
from uuid import uuid4

from app.schemas.audio import AudioSegment, AudioTranscriptionResponse
from app.services.audio_transcription import (
    AudioDurationLimitError, AudioNoSpeechDetectedError, AudioTranscriptionRuntimeError,
    AudioTranscriptionUnavailable,
)
from app.services.upload_validation import UploadValidationError, ValidatedUpload

MODEL = "gpt-4o-transcribe-diarize"
MAX_CHUNK_BYTES = 2_000_000


from app.services.hosted_audio import validate_references, wav_duration


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
                return AudioTranscriptionResponse(transcription_id=f"transcription_{uuid4().hex}",
                    filename=upload.filename, runtime_mode="real", transcription_engine="openai",
                    diarization_model=model, duration_seconds=duration, language="ko",
                    transcript_text="", error_codes=["no_speech"],
                    warnings=["발화가 감지되지 않은 구간은 원음으로 확인해주세요."],
                    stage_metrics={"total_seconds": time.perf_counter() - started})
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
