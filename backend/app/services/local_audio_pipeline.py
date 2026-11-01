"""Bounded local ASR and independent speaker clustering. No hosted inference.

Uploaded audio belongs to the route. Decoded PCM belongs to this service's
TemporaryDirectory and is deleted on both success and exception. Raw text and
stage artifacts are returned in memory; this service never persists transcripts.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from typing import Any
from uuid import uuid4

from app.schemas.audio import AudioInterval, AudioSegment, AudioTranscriptionResponse, AudioWord

RATE = 16000
DIARIZATION_WARNING = "화자 구분 확인 필요: 음성 인식 결과는 보존되었습니다."


@dataclass(frozen=True)
class LocalAudioConfig:
    engine: str = "faster-whisper"
    model: str = "large-v3"
    device: str = "cpu"
    compute_type: str = "int8"
    beam_size: int = 1
    batch_size: int = 1
    cpu_threads: int = 4
    chunk_seconds: float = 120
    context_seconds: float = 5
    max_duration_seconds: float = 3600
    diarization: str = "campplus"
    use_itn: bool = True
    whisper_vad_mode: str = "clips"
    hallucination_silence_seconds: float | None = None

    @classmethod
    def from_env(cls) -> "LocalAudioConfig":
        engine = os.getenv("AUDIO_TRANSCRIPTION_ENGINE", "faster-whisper")
        device = os.getenv("AUDIO_DEVICE", "cpu")
        config = cls(engine=engine,
                     model=os.getenv("AUDIO_MODEL", "large-v3" if engine == "faster-whisper" else "FunAudioLLM/SenseVoiceSmall"),
                     device=device, compute_type=os.getenv("AUDIO_COMPUTE_TYPE", "int8" if device == "cpu" else "float16"),
                     beam_size=int(os.getenv("AUDIO_BEAM_SIZE", "1")), batch_size=int(os.getenv("AUDIO_BATCH_SIZE", "4" if device != "cpu" and engine == "faster-whisper" else "1")),
                     cpu_threads=int(os.getenv("AUDIO_CPU_THREADS", "4")),
                     chunk_seconds=float(os.getenv("AUDIO_CHUNK_SECONDS", "120")),
                     context_seconds=float(os.getenv("AUDIO_CONTEXT_SECONDS", "5")),
                     max_duration_seconds=float(os.getenv("AUDIO_MAX_DURATION_SECONDS", "3600")),
                     diarization=os.getenv("AUDIO_DIARIZATION_ENGINE", "campplus"),
                     whisper_vad_mode=os.getenv("AUDIO_WHISPER_VAD_MODE", "clips"),
                     hallucination_silence_seconds=float(os.environ["AUDIO_HALLUCINATION_SILENCE_SECONDS"]) if os.getenv("AUDIO_HALLUCINATION_SILENCE_SECONDS") else None,
                     use_itn=os.getenv("AUDIO_USE_ITN", "1") == "1")
        config.validate()
        return config

    def validate(self) -> None:
        if self.engine not in {"faster-whisper", "sensevoice"} or self.diarization not in {"campplus", "disabled"}:
            raise ValueError("Unsupported local audio engine")
        if self.whisper_vad_mode not in {"concatenate", "segments", "clips"}:
            raise ValueError("Unsupported Whisper VAD mode")
        if self.hallucination_silence_seconds is not None and not 0.1 <= self.hallucination_silence_seconds <= 2:
            raise ValueError("Invalid hallucination silence threshold")
        if self.batch_size != 1 and (self.engine == "sensevoice" or self.whisper_vad_mode == "segments" or self.hallucination_silence_seconds is not None):
            raise ValueError("Independent utterances and hallucination timing checks require batch size 1")
        if self.whisper_vad_mode == "clips" and self.hallucination_silence_seconds is not None:
            raise ValueError("Batched clip decoding does not support hallucination silence filtering")
        if not 1 <= self.batch_size <= 16 or not 1 <= self.beam_size <= 10 or not 1 <= self.cpu_threads <= 32:
            raise ValueError("Invalid audio batch, beam or thread configuration")
        if not 30 <= self.chunk_seconds <= 300 or not 0 <= self.context_seconds <= 5 or not 1 <= self.max_duration_seconds <= 7200:
            raise ValueError("Invalid audio duration configuration")


def chunk_ranges(duration: float, seconds: float, context: float):
    """Half-open core ownership; context may be decoded twice but never owned twice."""
    core_start = 0.0
    while core_start < duration:
        core_end = min(duration, core_start + seconds)
        yield max(0.0, core_start - context), min(duration, core_end + context), core_start, core_end
        core_start = core_end


def owned_segment(segment: AudioSegment, offset: float, core_start: float, core_end: float) -> AudioSegment | None:
    """Own timestamped words by midpoint, otherwise retain the whole ASR segment."""
    valid_words = [w for w in segment.words if w.start is not None and w.end is not None]
    if valid_words:
        words = [w.model_copy(update={"start": w.start + offset, "end": w.end + offset}) for w in valid_words
                 if core_start <= (w.start + w.end) / 2 + offset < core_end]
        if not words:
            return None
        return segment.model_copy(update={"start": words[0].start, "end": words[-1].end,
                                          "text": "".join(w.text for w in words).strip(), "words": words})
    if core_start <= (segment.start + segment.end) / 2 + offset < core_end:
        return segment.model_copy(update={"start": segment.start + offset, "end": segment.end + offset})
    return None


def normalize_text(text: str) -> str:
    # No lexical substitution, filler removal, ITN or semantic repair here.
    return re.sub(r"\s+", " ", text).strip()


def coalesce_speech(spans: list[AudioInterval]) -> list[AudioInterval]:
    """Reconnect VAD spans clipped at a processing boundary before embedding them."""
    result = []
    for span in sorted(spans, key=lambda s: s.start):
        if result and span.start <= result[-1].end + 0.02:
            result[-1].end = max(result[-1].end, span.end)
        else:
            result.append(span.model_copy())
    return result


def uncovered_speech(raw: list[AudioSegment], speech: list[AudioInterval]) -> list[AudioInterval]:
    """Flag acoustic coverage gaps, without asserting what was said or inventing text.

    Word timing can itself be inaccurate. These are review candidates, not proven
    omissions. Coarse ASR segment timing provides only a weaker coverage check.
    """
    covered = []
    for segment in raw:
        words = [w for w in segment.words if w.start is not None and w.end is not None]
        if words:
            covered.extend((w.start, w.end) for w in words)
        else:
            covered.append((segment.start, segment.end))
    covered.sort()
    candidates = []
    for span in coalesce_speech(speech):
        cursor = span.start
        for start, end in covered:
            if end <= cursor:
                continue
            if start >= span.end:
                break
            if start - cursor >= 1.5:
                candidates.append(AudioInterval(start=cursor, end=min(start, span.end), code="speech_without_text"))
            cursor = max(cursor, min(end, span.end))
        if span.end - cursor >= 1.5:
            candidates.append(AudioInterval(start=cursor, end=span.end, code="speech_without_text"))
    return candidates


def speaker_at(start: float, end: float, spans: list[AudioInterval]) -> tuple[str | None, bool]:
    overlap: dict[str, float] = {}
    for span in spans:
        amount = max(0.0, min(end, span.end) - max(start, span.start))
        if span.speaker and amount:
            overlap[span.speaker] = overlap.get(span.speaker, 0) + amount
    if not overlap:
        return None, True
    winner = max(overlap, key=overlap.get)
    ratio = overlap[winner] / max(end - start, 0.001)
    return winner, ratio < 0.65 or len(overlap) > 1


def merge_speakers(raw: list[AudioSegment], spans: list[AudioInterval]) -> list[AudioSegment]:
    """Assign acoustic labels at word boundaries without guessing missing timestamps."""
    result: list[AudioSegment] = []
    for segment in raw:
        units = segment.words or [AudioWord(start=segment.start, end=segment.end, text=segment.text, probability=segment.confidence)]
        groups: list[dict] = []
        for word in units:
            start = word.start if word.start is not None else segment.start
            end = word.end if word.end is not None else segment.end
            speaker, uncertain = speaker_at(start, end, spans)
            if groups and groups[-1]["speaker"] == speaker and start - groups[-1]["end"] <= 0.8:
                group = groups[-1]
                group["end"] = end
                group["text"] += word.text
                group["uncertain"] |= uncertain
                group["words"].append(word)
            else:
                groups.append(dict(start=start, end=end, text=word.text, speaker=speaker, uncertain=uncertain, words=[word]))
        for group in groups:
            text = normalize_text(group["text"])
            if not text:
                continue
            probs = [w.probability for w in group["words"] if w.probability is not None]
            confidence = sum(probs) / len(probs) if probs else segment.confidence
            flags = list(segment.review_flags)
            if group["uncertain"]:
                flags.append("speaker_uncertain")
            if confidence is not None and confidence < 0.75:
                flags.append("low_confidence")
            if (confidence is None or confidence < 0.85) and re.search(r"안\s|않|못\s|없|\d|약|진단|자해|죽|이름|병원|센터", text):
                flags.append("sensitive_expression")
            if not segment.words and len({s.speaker for s in spans if s.start < group['end'] and s.end > group['start']}) > 1:
                flags.append("mixed_speakers_without_word_timestamps")
            result.append(AudioSegment(id=len(result) + 1, segment_id=f"turn-{len(result):06d}",
                                       start=group["start"], end=group["end"], text=text, speaker=group["speaker"],
                                       confidence=confidence, words=group["words"] if segment.words else [],
                                       source_segment_ids=[segment.segment_id or str(segment.id)],
                                       review_flags=sorted(set(flags))))
    turns: list[AudioSegment] = []
    for segment in result:
        if (turns and segment.speaker is not None and turns[-1].speaker == segment.speaker
                and 0 <= segment.start - turns[-1].end <= 3.0
                and not any(s.speaker != segment.speaker and s.start < segment.start and s.end > turns[-1].end for s in spans)):
            previous = turns[-1]
            previous.end = segment.end
            previous.text = normalize_text(previous.text + " " + segment.text)
            previous.words.extend(segment.words)
            previous.review_flags = sorted(set(previous.review_flags + segment.review_flags))
            previous.source_segment_ids = list(dict.fromkeys(previous.source_segment_ids + segment.source_segment_ids))
            probabilities = [w.probability for w in previous.words if w.probability is not None]
            previous.confidence = sum(probabilities) / len(probabilities) if probabilities else None
        else:
            turns.append(segment.model_copy(deep=True))
    for i, segment in enumerate(turns):
        segment.id, segment.segment_id = i + 1, f"turn-{i:06d}"
    return turns


def _read_audio(path: Path, start: float, end: float):
    import soundfile as sf
    with sf.SoundFile(path) as stream:
        stream.seek(round(start * RATE))
        return stream.read(round((end - start) * RATE), dtype="float32")


def decode_audio_file(source: Path, target: Path, max_duration: float) -> float:
    import soundfile as sf
    from app.services.audio_transcription import AudioDurationLimitError, AudioTranscriptionRuntimeError, DURATION_LIMIT_ERROR
    # Bound both disk use and decode wall time; never pass a user filename to a shell.
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
               "-t", str(max_duration + 1), "-vn", "-ac", "1", "-ar", str(RATE), "-c:a", "pcm_s16le", str(target)]
    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=300)
        duration = sf.info(target).duration
    except (OSError, subprocess.SubprocessError, RuntimeError) as error:
        raise AudioTranscriptionRuntimeError("오디오를 해독하지 못했습니다. 파일 형식을 확인해주세요.") from error
    if duration > max_duration:
        raise AudioDurationLimitError(DURATION_LIMIT_ERROR)
    return duration


class LocalAudioPipeline:
    def __init__(self, config: LocalAudioConfig, progress=None):
        config.validate()
        self.config = config
        self.asr: Any = None
        self.vad: Any = None
        self.speaker_model: Any = None
        self.progress = progress or (lambda event: None)

    def _load_asr(self):
        if self.asr is not None:
            return
        if self.config.engine == "faster-whisper":
            from faster_whisper import WhisperModel
            self.asr = WhisperModel(self.config.model, device=self.config.device, compute_type=self.config.compute_type,
                                    cpu_threads=self.config.cpu_threads, num_workers=1)
        else:
            from funasr import AutoModel
            self.asr = AutoModel(model=self.config.model, hub="hf", device=self.config.device,
                                 disable_update=True, disable_pbar=True, ncpu=self.config.cpu_threads,
                                 trust_remote_code=False)
            self.vad = AutoModel(model=os.getenv("AUDIO_FSMN_MODEL", "funasr/fsmn-vad"), hub="hf", device="cpu",
                                 disable_update=True, disable_pbar=True, ncpu=self.config.cpu_threads,
                                 max_single_segment_time=28000, trust_remote_code=False)

    def recognize(self, audio) -> tuple[list[AudioSegment], list[AudioInterval]]:
        self._load_asr()
        segments = []
        if self.config.engine == "faster-whisper":
            from faster_whisper.vad import get_speech_timestamps, VadOptions
            vad_params = dict(min_silence_duration_ms=200, speech_pad_ms=200, min_speech_duration_ms=80,
                              max_speech_duration_s=28)
            detected = get_speech_timestamps(audio, VadOptions(**vad_params))
            spans = [AudioInterval(start=s["start"] / RATE, end=s["end"] / RATE) for s in detected]
            separate = self.config.whisper_vad_mode == "segments"
            # Independent VAD utterances prevent a quiet turn from being decoded
            # in the same Whisper context as an unrelated louder turn.
            inputs = [(span.start, audio[round(span.start * RATE):round(span.end * RATE)]) for span in spans] if separate else [(0.0, audio)]
            for offset, samples in inputs:
                kwargs = dict(language="ko", task="transcribe", beam_size=self.config.beam_size, temperature=0,
                              condition_on_previous_text=False, word_timestamps=True, vad_filter=not separate, vad_parameters=vad_params,
                              hallucination_silence_threshold=self.config.hallucination_silence_seconds)
                if self.config.whisper_vad_mode == "clips":
                    if not spans:
                        continue
                    from faster_whisper import BatchedInferencePipeline
                    kwargs.update(vad_filter=False, clip_timestamps=[{"start": span.start, "end": span.end} for span in spans])
                    iterator, _ = BatchedInferencePipeline(self.asr).transcribe(samples, batch_size=self.config.batch_size, **kwargs)
                elif self.config.batch_size > 1 and not separate:
                    from faster_whisper import BatchedInferencePipeline
                    iterator, _ = BatchedInferencePipeline(self.asr).transcribe(samples, batch_size=self.config.batch_size, **kwargs)
                else:
                    iterator, _ = self.asr.transcribe(samples, **kwargs)
                for s in iterator:
                    words = [AudioWord(start=w.start + offset, end=w.end + offset, text=w.word, probability=w.probability) for w in (s.words or [])]
                    flags = ["repetition_candidate"] if s.compression_ratio > 2.4 else []
                    letters = sum(c.isalnum() for c in s.text)
                    if letters >= 6 and letters / max(s.end - s.start, 0.05) > 20:
                        flags.append("timestamp_anomaly")
                    segments.append(AudioSegment(id=len(segments), start=s.start + offset, end=s.end + offset, text=s.text,
                                                 confidence=max(0, min(1, math.exp(s.avg_logprob))), words=words, review_flags=flags))
            return segments, spans
        detected = self.vad.generate(input=audio, cache={}, is_final=True, disable_pbar=True)[0].get("value", [])
        spans = []
        for start_ms, end_ms in detected:
            start, end = max(0.0, start_ms / 1000), min(len(audio) / RATE, end_ms / 1000)
            # SenseVoice's official direct inference contract is <=30 seconds.
            while start < end:
                stop = min(start + 28, end)
                spans.append(AudioInterval(start=start, end=stop))
                result = self.asr.generate(input=audio[round(start * RATE):round(stop * RATE)], cache={},
                                           language="ko", use_itn=self.config.use_itn, batch_size=1, disable_pbar=True)
                text = re.sub(r"<\|[^>]*\|>", "", result[0].get("text", "")).strip()
                if text:
                    segments.append(AudioSegment(id=len(segments), start=start, end=stop, text=text,
                                                 review_flags=["coarse_timestamps"]))
                start = stop
        return segments, spans

    def diarize(self, path: Path, speech: list[AudioInterval], expected_speakers: int) -> list[AudioInterval]:
        import numpy as np
        from funasr import AutoModel
        from sklearn.cluster import AgglomerativeClustering
        if self.speaker_model is None:
            self.speaker_model = AutoModel(model=os.getenv("AUDIO_CAMPPLUS_MODEL", "funasr/campplus"), hub="hf",
                                           device=self.config.device, disable_update=True, disable_pbar=True,
                                           ncpu=self.config.cpu_threads, trust_remote_code=False)
        windows = []
        embeddings = []
        durations = []
        for span in coalesce_speech(speech):
            if span.end - span.start < 0.12:
                continue
            starts = [span.start] if span.end - span.start <= 2 else list(np.arange(span.start, span.end - 1.49, 0.75))
            if not starts:
                starts = [span.start]
            if starts[-1] + 1.5 < span.end and span.end - span.start > 2:
                starts.append(span.end - 1.5)
            centers = [(s + min(s + 1.5, span.end)) / 2 for s in starts]
            for i, start in enumerate(starts):
                end = span.end if len(starts) == 1 else min(start + 1.5, span.end)
                samples = _read_audio(path, start, end)
                if len(samples) < RATE // 2:
                    samples = np.pad(samples, (0, RATE // 2 - len(samples)))
                value = self.speaker_model.generate(input=samples, disable_pbar=True)[0]["spk_embedding"]
                embedding = value.detach().cpu().numpy() if hasattr(value, "detach") else np.asarray(value)
                embeddings.append(embedding.reshape(-1))
                durations.append(end - start)
                if len(embeddings) % 100 == 0:
                    self.progress({"stage": "diarization", "windows": len(embeddings)})
                left = span.start if i == 0 else (centers[i - 1] + centers[i]) / 2
                right = span.end if i + 1 == len(starts) else (centers[i] + centers[i + 1]) / 2
                windows.append((left, right))
        if len(embeddings) < expected_speakers:
            raise ValueError("Insufficient speech for requested speaker count")
        vectors = np.asarray(embeddings)
        vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-8)
        # Bound quadratic clustering memory; assign remaining windows to centroids.
        # Tiny backchannels/padded boundary fragments are classified AFTER fitting;
        # they must not consume a speaker cluster as acoustic outliers.
        eligible = np.flatnonzero(np.asarray(durations) >= 1.0)
        if len(eligible) < expected_speakers:
            raise ValueError("Insufficient stable speech for speaker clustering")
        sample_indices = eligible[np.linspace(0, len(eligible) - 1, min(2048, len(eligible)), dtype=int)]
        sample = vectors[sample_indices]
        labels = AgglomerativeClustering(n_clusters=expected_speakers, metric="cosine", linkage="average").fit_predict(sample) if expected_speakers > 1 else np.zeros(len(sample), dtype=int)
        centroids = np.stack([sample[labels == i].mean(axis=0) for i in range(expected_speakers)])
        centroids /= np.maximum(np.linalg.norm(centroids, axis=1, keepdims=True), 1e-8)
        labels = (vectors @ centroids.T).argmax(axis=1)
        names: dict[int, str] = {}
        result = []
        for (start, end), label in zip(windows, labels):
            speaker = names.setdefault(int(label), f"speaker_{len(names)}")
            if result and result[-1].speaker == speaker and abs(result[-1].end - start) < 0.02:
                result[-1].end = end
            else:
                result.append(AudioInterval(start=start, end=end, speaker=speaker))
        return result

    def transcribe(self, upload, *, language=None, task="transcribe", expected_speakers=2):
        from app.services.audio_transcription import (_audio_job_slot, AudioNoSpeechDetectedError,
                                                      AudioTranscriptionRuntimeError, NO_SPEECH_ERROR)
        if language not in {None, "ko"} or task != "transcribe" or not 1 <= expected_speakers <= 4:
            raise ValueError("Korean transcription and 1-4 speakers are required")
        started = time.perf_counter()
        with _audio_job_slot(1), tempfile.TemporaryDirectory(prefix="remind_pcm_", dir=os.getenv("UPLOAD_TMP_DIR") or None) as directory:
            pcm = Path(directory) / "decoded.wav"
            duration = decode_audio_file(upload.temp_path, pcm, self.config.max_duration_seconds)
            metrics = {"decode_seconds": time.perf_counter() - started}
            raw: list[AudioSegment] = []
            vad: list[AudioInterval] = []
            failed = []
            errors = []
            asr_started = time.perf_counter()
            for left, right, core_start, core_end in chunk_ranges(duration, self.config.chunk_seconds, self.config.context_seconds):
                try:
                    segments, spans = self.recognize(_read_audio(pcm, left, right))
                    for segment in segments:
                        owned = owned_segment(segment, left, core_start, core_end)
                        if owned is not None and owned.text.strip():
                            owned.id = len(raw) + 1
                            owned.segment_id = f"asr-{len(raw):06d}"
                            raw.append(owned)
                    for s in spans:
                        start, end = max(core_start, s.start + left), min(core_end, s.end + left)
                        if end > start:
                            vad.append(AudioInterval(start=start, end=end))
                except Exception as error:
                    code = "gpu_oom" if "out of memory" in str(error).lower() else "asr_failed"
                    failed.append(AudioInterval(start=core_start, end=core_end, code=code))
                    errors.append(code)
                    if code == "gpu_oom":
                        if core_end < duration:
                            failed.append(AudioInterval(start=core_end, end=duration, code="not_processed"))
                        break
                self.progress({"stage": "asr", "processed_seconds": core_end, "duration_seconds": duration, "segments": len(raw)})
            metrics["asr_seconds"] = time.perf_counter() - asr_started
            if not raw:
                if errors:
                    message = "GPU 메모리가 부족합니다. 배치 크기를 줄여 다시 시도해주세요." if "gpu_oom" in errors else "음성 인식에 실패했습니다. 로컬 모델과 실행 환경을 확인해주세요."
                    raise AudioTranscriptionRuntimeError(message)
                raise AudioNoSpeechDetectedError(NO_SPEECH_ERROR)
            raw.sort(key=lambda s: (s.start, s.end))
            diarization = []
            warnings = []
            status = "disabled"
            diar_started = time.perf_counter()
            if self.config.diarization != "disabled":
                try:
                    diarization = self.diarize(pcm, vad, expected_speakers)
                    status = "completed"
                except Exception as error:
                    status = "fallback"
                    errors.append("diarization_failed")
                    warnings.append(DIARIZATION_WARNING)
                    if "out of memory" in str(error).lower():
                        errors.append("gpu_oom")
                        warnings.append("화자 분리 중 GPU 메모리가 부족했습니다. 보존된 축어록에서 화자를 직접 확인해주세요.")
            else:
                warnings.append(DIARIZATION_WARNING)
            metrics["diarization_seconds"] = time.perf_counter() - diar_started
            segments = merge_speakers(raw, diarization)
            review_ranges = uncovered_speech(raw, vad)
            if review_ranges:
                warnings.append("음성이 감지됐지만 텍스트와 연결되지 않은 구간이 있습니다. 원음에서 누락 여부를 확인해주세요.")
            if failed:
                warnings.append("일부 구간만 처리되었습니다. 누락된 시간 구간을 확인해주세요.")
            if any(s.review_flags for s in segments):
                warnings.append("확인이 필요한 발화가 있습니다. 원음을 듣고 수정해주세요.")
            metrics["total_seconds"] = time.perf_counter() - started
            metrics["real_time_factor"] = metrics["total_seconds"] / max(duration, 0.001)
            return AudioTranscriptionResponse(transcription_id=f"transcription_{uuid4().hex}", filename=upload.filename,
                status="partial" if failed else "completed", runtime_mode="real", transcription_engine=self.config.engine,
                duration_seconds=duration, language="ko", alignment_status="disabled", diarization_status=status,
                diarization_model=self.config.diarization, segments=segments, raw_segments=raw, vad_segments=vad,
                diarization_segments=diarization, failed_ranges=failed, error_codes=sorted(set(errors)), stage_metrics=metrics,
                review_ranges=review_ranges, transcript_text="\n".join(s.text for s in segments), warnings=warnings)
