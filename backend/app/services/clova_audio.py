"""CLOVA Speech adapter with bounded, memory-only reference context.

CLOVA does not accept known-speaker IDs. Short reference clips are prepended to
each request; only unique, dominant timestamp matches establish speaker identity.
Reference text is removed before returning the actual chunk. Ambiguity is reviewed,
never resolved from provider label order or the meaning of the conversation.
"""
from __future__ import annotations

import base64
from collections import Counter
import io
import json
import math
import os
import re
import time
import wave
from uuid import uuid4

import httpx

from app.schemas.audio import AudioInterval, AudioSegment, AudioTranscriptionResponse, AudioWord
from app.services.audio_transcription import (
    AudioDurationLimitError, AudioTranscriptionRuntimeError, AudioTranscriptionUnavailable,
)
from app.services.hosted_audio import validate_references, wav_duration
from app.services.upload_validation import UploadValidationError, ValidatedUpload


def clova_config() -> tuple[str, str]:
    url = os.getenv("CLOVA_SPEECH_INVOKE_URL", "").strip().rstrip("/")
    key = os.getenv("CLOVA_SPEECH_SECRET_KEY", "").strip()
    # The domain-specific path is secret configuration, never client input/log output.
    if not key or not re.fullmatch(r"https://clovaspeech-gw\.ncloud\.com/external/v1/[0-9]+/[A-Za-z0-9_-]+", url):
        raise AudioTranscriptionUnavailable("CLOVA Speech 연결 설정이 필요합니다.")
    return url, key


def _frames(data: bytes) -> bytes:
    with wave.open(io.BytesIO(data), "rb") as audio:
        return audio.readframes(audio.getnframes())


def _with_references(data: bytes, references: list[dict]) -> tuple[bytes, list[tuple], float]:
    names, clips = validate_references(references)
    parts, intervals = [], []
    offset = 0.0
    for name, clip in zip(names, clips):
        pcm = _frames(base64.b64decode(clip.split(",", 1)[1], validate=True))
        duration = len(pcm) / 32000
        intervals.append((name, offset, offset + duration))
        parts.extend([pcm, b"\0\0" * 8000])
        offset += duration + 0.5
    if not parts:
        return data, intervals, offset
    parts.append(_frames(data))
    result = io.BytesIO()
    with wave.open(result, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"".join(parts))
    return result.getvalue(), intervals, offset


def _label(item: dict) -> str | None:
    value = (item.get("diarization") or {}).get("label")
    return str(value) if value is not None else None


def _times(start, end, limit: float) -> tuple[float, float]:
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (start, end)):
        raise AudioTranscriptionRuntimeError("CLOVA Speech 시간 정보가 올바르지 않습니다.")
    start, end = start / 1000, end / 1000
    if not (0 <= start < end <= limit + 1 and start < limit):
        raise AudioTranscriptionRuntimeError("CLOVA Speech 시간 정보가 올바르지 않습니다.")
    return start, min(end, limit)


def _speaker_map(items: list[dict], intervals: list[tuple]) -> dict[str, str]:
    proposals = []
    for name, start, end in intervals:
        scores = Counter()
        for item in items:
            label = _label(item)
            if label is not None:
                scores[label] += max(0, min(end, item["end"] / 1000) - max(start, item["start"] / 1000))
        ranked = scores.most_common()
        if ranked and ranked[0][1] >= max(0.5, (end - start) * 0.4) and ranked[0][1] >= sum(scores.values()) * 0.85:
            proposals.append((ranked[0][0], name))
    counts = Counter(label for label, _ in proposals)
    return {label: name for label, name in proposals if counts[label] == 1}


def parse_clova(payload: dict, duration: float, intervals: list[tuple], offset: float) -> tuple[list, list, list]:
    items = payload.get("segments") or []
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise AudioTranscriptionRuntimeError("CLOVA Speech 응답 형식이 올바르지 않습니다.")
    for item in items:
        _times(item.get("start"), item.get("end"), duration + offset)
    mapping = _speaker_map(items, intervals)
    segments, raw, failed = [], [], []
    for item in items:
        start, end = _times(item["start"], item["end"], duration + offset)
        if end <= offset:
            continue
        words = []
        for word in item.get("words") or []:
            if not isinstance(word, list) or len(word) != 3 or not isinstance(word[2], str):
                raise AudioTranscriptionRuntimeError("CLOVA Speech 단어 시간 정보가 올바르지 않습니다.")
            ws, we = _times(word[0], word[1], duration + offset)
            if ws >= offset:
                words.append(AudioWord(start=ws-offset, end=we-offset, text=word[2]))
        text = str(item.get("text") or "").strip()
        flags = []
        if start < offset:
            # A provider segment can span reference and actual audio. Word alignment
            # is the only allowed way to discard reference text without guessing.
            flags.append("reference_boundary")
            if not words:
                failed.append(AudioInterval(start=0, end=end-offset, code="timestamp_unavailable"))
                continue
            text = " ".join(word.text for word in words)
            start = offset + words[0].start
        if not text:
            continue
        confidence = item.get("confidence")
        if not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            confidence = None
        if confidence is not None and confidence < 0.8:
            flags.append("low_confidence")
        label = _label(item)
        speaker = mapping.get(label) if intervals else (f"clova_{label}" if label is not None else None)
        if speaker is None:
            flags.append("speaker_reference_unmatched" if intervals else "speaker_unassigned")
            if label is not None:
                speaker = f"unmatched_{label}"
        segment = AudioSegment(id=len(segments), segment_id=f"seg_{len(segments)}", start=max(0, start-offset),
            end=end-offset, text=text, speaker=speaker, confidence=confidence, words=words, review_flags=flags)
        segments.append(segment)
        raw.append(segment.model_copy(update={"speaker": label}, deep=True))
    if not segments and str(payload.get("text") or "").strip() and not items:
        if offset:
            raise AudioTranscriptionRuntimeError("CLOVA Speech 화자 참조와 본문을 구분하지 못했습니다. 구간을 다시 처리해주세요.")
        segment = AudioSegment(id=0, segment_id="seg_0", start=0, end=duration,
            text=payload["text"].strip(), review_flags=["speaker_unassigned", "timestamp_unavailable"])
        segments.append(segment)
        raw.append(segment.model_copy(deep=True))
    segments.sort(key=lambda s: (s.start, s.end))
    raw.sort(key=lambda s: (s.start, s.end))
    return segments, raw, failed


class ClovaAudioTranscriptionService:
    def transcribe(self, upload: ValidatedUpload, *, language=None, task="transcribe",
                   expected_speakers=2, speaker_references=None) -> AudioTranscriptionResponse:
        url, key = clova_config()
        if upload.suffix != ".wav" or upload.size_bytes > 2_000_000:
            raise UploadValidationError(413, "음성을 60초 이하 WAV 구간으로 나누어 업로드해주세요.")
        duration = wav_duration(str(upload.temp_path))
        if not 0 < duration <= 60:
            raise AudioDurationLimitError("음성 구간은 60초 이하여야 합니다.")
        media, intervals, offset = _with_references(upload.temp_path.read_bytes(), speaker_references or [])
        params = {"language": "ko-KR", "completion": "sync", "wordAlignment": True, "fullText": True,
            "resultToObs": False, "diarization": {"enable": True, "speakerCountMin": 1,
                "speakerCountMax": expected_speakers}, "sed": {"enable": False}}
        # Optional domain vocabulary is administrator configuration, never a text rewrite.
        keywords = [s.strip() for s in os.getenv("CLOVA_SPEECH_KEYWORDS", "").split(",") if s.strip()]
        if keywords:
            if len(keywords) > 100 or any(len(s) > 80 for s in keywords):
                raise AudioTranscriptionUnavailable("CLOVA Speech 키워드 설정을 확인해주세요.")
            params["boostings"] = [{"words": ",".join(keywords), "weight": 1}]
        started = time.perf_counter()
        try:
            # Redirects could disclose the secret header/audio to another host.
            with httpx.Client(timeout=240, follow_redirects=False) as client:
                response = client.post(url + "/recognizer/upload", headers={"X-CLOVASPEECH-API-KEY": key},
                    files={"media": ("chunk.wav", media, "audio/wav"),
                        "params": (None, json.dumps(params, ensure_ascii=False), "application/json")})
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise AudioTranscriptionRuntimeError("CLOVA Speech 처리에 실패했습니다. 연결 또는 사용 한도를 확인해주세요.") from error
        if (not isinstance(payload, dict) or payload.get("result") not in {"COMPLETED", "SUCCEEDED"}
                or not ({"segments", "text"} & payload.keys())):
            raise AudioTranscriptionRuntimeError("CLOVA Speech 인식이 완료되지 않았습니다. 다시 시도해주세요.")
        try:
            segments, raw, failed = parse_clova(payload, duration, intervals, offset)
        except (TypeError, AttributeError, KeyError) as error:
            raise AudioTranscriptionRuntimeError("CLOVA Speech 응답 형식이 올바르지 않습니다.") from error
        codes = ["partial_transcription"] if failed else []
        fallback = any(set(s.review_flags) & {"speaker_unassigned", "speaker_reference_unmatched"} for s in segments)
        if fallback:
            codes.append("diarization_failed")
        if not segments and not failed:
            codes.append("no_speech")
        return AudioTranscriptionResponse(transcription_id=f"transcription_{uuid4().hex}",
            filename=upload.filename, runtime_mode="real", transcription_engine="clova",
            diarization_model="clova-speech", diarization_status="fallback" if fallback else "completed",
            alignment_status="completed" if all(s.words for s in segments) else "fallback",
            duration_seconds=duration, language="ko", segments=segments, raw_segments=raw,
            status="partial" if failed else "completed", failed_ranges=failed,
            transcript_text="\n".join(s.text for s in segments), error_codes=codes,
            warnings=["자동 화자 및 숫자·부정·고유명사를 원음과 대조해주세요.",
                *(["발화가 감지되지 않은 구간은 원음으로 확인해주세요."] if "no_speech" in codes else [])],
            stage_metrics={"total_seconds": time.perf_counter()-started, "reference_seconds": offset})
