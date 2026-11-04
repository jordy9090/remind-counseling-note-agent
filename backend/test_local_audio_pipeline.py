"""Behavioral tests for bounded processing, failure isolation and privacy lifecycle."""
from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import wave

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.audio import router
from app.api.security import require_preview_access
from app.schemas.audio import AudioInterval, AudioSegment, AudioWord
from app.services.audio_transcription import AudioDurationLimitError, AudioNoSpeechDetectedError, AudioTranscriptionRuntimeError
from app.services.local_audio_pipeline import LocalAudioConfig, LocalAudioPipeline, chunk_ranges, coalesce_speech, merge_speakers, normalize_text, owned_segment, uncovered_speech
from app.services.upload_validation import ValidatedUpload


class LocalAudioTests(unittest.TestCase):
    def test_default_runtime_uses_measured_clip_configuration(self):
        with patch.dict('os.environ', {}, clear=True):
            cpu = LocalAudioConfig.from_env()
        with patch.dict('os.environ', {'AUDIO_DEVICE':'cuda'}, clear=True):
            gpu = LocalAudioConfig.from_env()
        with patch.dict('os.environ', {'AUDIO_DEVICE':'cuda','AUDIO_TRANSCRIPTION_ENGINE':'sensevoice'}, clear=True):
            sense = LocalAudioConfig.from_env()
        self.assertEqual(('clips',5,1,1),(cpu.whisper_vad_mode,cpu.context_seconds,cpu.batch_size,cpu.beam_size))
        self.assertEqual(('clips',5,4,'float16'),(gpu.whisper_vad_mode,gpu.context_seconds,gpu.batch_size,gpu.compute_type))
        self.assertEqual(1,sense.batch_size)

    def test_unsupported_batch_settings_are_not_silently_ignored(self):
        for config in (LocalAudioConfig(whisper_vad_mode="segments", batch_size=4),
                       LocalAudioConfig(hallucination_silence_seconds=0.5, batch_size=4),
                       LocalAudioConfig(engine="sensevoice", batch_size=4)):
            with self.assertRaises(ValueError):
                config.validate()

    def test_independent_vad_utterances_keep_offsets_and_do_not_reapply_vad(self):
        calls = []
        def transcribe(samples, **kwargs):
            calls.append((len(samples), kwargs))
            word = SimpleNamespace(start=0.1, end=0.9, word=" 안 갔다", probability=0.99)
            segment = SimpleNamespace(start=0.1, end=0.9, text=" 안 갔다", words=[word], compression_ratio=1, avg_logprob=-0.1)
            return iter([segment]), None
        service = LocalAudioPipeline(LocalAudioConfig(whisper_vad_mode="segments"))
        service.asr = SimpleNamespace(transcribe=transcribe)
        fake_vad = SimpleNamespace(VadOptions=lambda **kwargs: kwargs,
            get_speech_timestamps=lambda *args: [{'start':16000,'end':32000},{'start':48000,'end':64000}])
        with patch.dict('sys.modules', {'faster_whisper.vad':fake_vad}):
            segments, spans = service.recognize([0] * 64000)
        self.assertEqual([16000,16000], [n for n,_ in calls])
        self.assertTrue(all(not kwargs['vad_filter'] for _,kwargs in calls))
        self.assertEqual([1.1,3.1], [s.start for s in segments])
        self.assertEqual([1.9,3.9], [s.words[0].end for s in segments])
        self.assertEqual([1,3], [s.start for s in spans])

    def test_impossible_timing_is_flagged_without_lexical_deletion(self):
        calls = []
        text = "영상편집 및 광고를 포함합니다."
        def transcribe(samples, **kwargs):
            calls.append(kwargs)
            word = SimpleNamespace(start=0.5, end=0.6, word=text, probability=0.8)
            segment = SimpleNamespace(start=0.5, end=0.6, text=text, words=[word], compression_ratio=1, avg_logprob=-0.1)
            return iter([segment]), None
        service = LocalAudioPipeline(LocalAudioConfig(whisper_vad_mode="segments", hallucination_silence_seconds=0.5))
        service.asr = SimpleNamespace(transcribe=transcribe)
        fake_vad = SimpleNamespace(VadOptions=lambda **kwargs: kwargs,
            get_speech_timestamps=lambda *args: [{'start':0,'end':16000}])
        with patch.dict('sys.modules', {'faster_whisper.vad':fake_vad}):
            segments, _ = service.recognize([0] * 16000)
        self.assertEqual(0.5, calls[0]['hallucination_silence_threshold'])
        self.assertEqual(text, segments[0].text)
        self.assertIn('timestamp_anomaly', segments[0].review_flags)

    def test_batched_clips_use_exact_vad_spans_and_global_word_times(self):
        calls = []
        def transcribe(samples, **kwargs):
            calls.append(kwargs)
            word = SimpleNamespace(start=1.1, end=1.9, word=" 안 갔다", probability=0.99)
            segment = SimpleNamespace(start=1.1, end=1.9, text=" 안 갔다", words=[word], compression_ratio=1, avg_logprob=-0.1)
            return iter([segment]), None
        service = LocalAudioPipeline(LocalAudioConfig(whisper_vad_mode="clips", batch_size=4))
        service.asr = object()
        fake_vad = SimpleNamespace(VadOptions=lambda **kwargs: kwargs,
            get_speech_timestamps=lambda *args: [{'start':16000,'end':32000},{'start':48000,'end':64000}])
        fake_package = SimpleNamespace(BatchedInferencePipeline=lambda model: SimpleNamespace(transcribe=transcribe))
        with patch.dict('sys.modules', {'faster_whisper':fake_package,'faster_whisper.vad':fake_vad}):
            segments, _ = service.recognize([0] * 64000)
        self.assertEqual([{'start':1,'end':2},{'start':3,'end':4}],calls[0]['clip_timestamps'])
        self.assertFalse(calls[0]['vad_filter'])
        self.assertEqual(4,calls[0]['batch_size'])
        self.assertEqual((1.1,1.9),(segments[0].start,segments[0].words[0].end))

    def test_hour_chunks_have_exact_core_coverage_and_bounded_context(self):
        ranges = list(chunk_ranges(3600, 120, 2))
        self.assertEqual(30, len(ranges))
        self.assertEqual(3600, sum(end - start for _, _, start, end in ranges))
        self.assertTrue(all(right - left <= 124 for left, right, _, _ in ranges))
        self.assertTrue(all(a[3] == b[2] for a, b in zip(ranges, ranges[1:])))

    def test_vad_boundary_fragments_rejoin_without_mutating_stage_artifact(self):
        spans = [AudioInterval(start=118, end=120), AudioInterval(start=120, end=120.216), AudioInterval(start=121, end=124)]
        merged = coalesce_speech(spans)
        self.assertEqual([(118, 120.216), (121, 124)], [(s.start, s.end) for s in merged])
        self.assertEqual(120, spans[0].end)

    def test_boundary_word_owned_once_without_text_repair(self):
        word = AudioWord(start=119.8, end=120.2, text=" 안 갔다", probability=0.8)
        first = AudioSegment(id=1, start=119.8, end=120.2, text="안 갔다", words=[word])
        second = first.model_copy(update={"start": 1.8, "end": 2.2,
            "words": [word.model_copy(update={"start": 1.8, "end": 2.2})]})
        self.assertIsNone(owned_segment(first, 0, 0, 120))
        actual = owned_segment(second, 118, 120, 240)
        self.assertEqual("안 갔다", actual.text)
        self.assertAlmostEqual(119.8, actual.start)
        self.assertEqual("안 갔다 12회 에스시탈로프람", normalize_text(" 안  갔다\n12회 에스시탈로프람 "))

    def test_speaker_assignment_is_separate_and_unknown_is_not_a_role(self):
        raw = [AudioSegment(id=1, segment_id="raw-1", start=0, end=4, text="안 갔다 네", words=[
            AudioWord(start=0, end=1.5, text="안 갔다"), AudioWord(start=2, end=4, text=" 네")])]
        spans = [AudioInterval(start=0, end=1.5, speaker="speaker_0"), AudioInterval(start=2, end=4, speaker="speaker_1")]
        turns = merge_speakers(raw, spans)
        self.assertEqual(["speaker_0", "speaker_1"], [t.speaker for t in turns])
        self.assertEqual(["안 갔다", "네"], [t.text for t in turns])
        self.assertIsNone(raw[0].speaker)
        fallback = merge_speakers(raw, [])
        self.assertTrue(all(t.speaker is None and "speaker_uncertain" in t.review_flags for t in fallback))

    def test_coarse_asr_with_multiple_speakers_is_flagged_not_fabricated(self):
        raw = [AudioSegment(id=1, start=0, end=5, text="안 갔다. 네.")]
        result = merge_speakers(raw, [AudioInterval(start=0, end=3, speaker="speaker_0"), AudioInterval(start=3, end=5, speaker="speaker_1")])
        self.assertEqual(1, len(result))
        self.assertEqual(raw[0].text, result[0].text)
        self.assertIn("mixed_speakers_without_word_timestamps", result[0].review_flags)

    def test_sentence_pause_merges_but_intervening_backchannel_keeps_boundary(self):
        raw = [AudioSegment(id=1, start=0, end=1, text="안 갔다."),
               AudioSegment(id=2, start=2.5, end=4, text="못 갔다.")]
        spans = [AudioInterval(start=0, end=1, speaker="speaker_0"),
                 AudioInterval(start=2.5, end=4, speaker="speaker_0")]
        merged = merge_speakers(raw, spans)
        self.assertEqual(1, len(merged))
        self.assertEqual("안 갔다. 못 갔다.", merged[0].text)
        self.assertEqual((0, 4), (merged[0].start, merged[0].end))
        spans.append(AudioInterval(start=1.5, end=1.8, speaker="speaker_1"))
        self.assertEqual(2, len(merge_speakers(raw, spans)))

    def test_uncovered_speech_is_flagged_without_reconstructing_missing_text(self):
        raw = [AudioSegment(id=1, start=120, end=126, text="네", words=[AudioWord(start=123.4, end=126, text="네")])]
        gaps = uncovered_speech(raw, [AudioInterval(start=121, end=125)])
        self.assertEqual([(121, 123.4, "speech_without_text")], [(s.start, s.end, s.code) for s in gaps])
        self.assertEqual("네", raw[0].text)
        self.assertEqual([], uncovered_speech(raw, [AudioInterval(start=123.2, end=126)]))

    def _run_fake(self, failures=(), diar_failure=False, duration=245, no_speech=False, failure_message="synthetic error"):
        service = LocalAudioPipeline(LocalAudioConfig(context_seconds=2))
        calls = []
        folders = []
        def decode(source, target, maximum):
            folders.append(target.parent)
            target.write_bytes(b"synthetic decoded PCM")
            return duration
        def recognize(audio):
            index = len(calls)
            calls.append(index)
            if index in failures:
                raise RuntimeError(failure_message)
            if no_speech:
                return [], []
            return [AudioSegment(id=1, start=3, end=4, text="안 갔다")], [AudioInterval(start=3, end=4)]
        service.recognize = recognize
        service.diarize = lambda *args: (_ for _ in ()).throw(RuntimeError(failure_message)) if diar_failure else [AudioInterval(start=0, end=duration, speaker="speaker_0")]
        upload = ValidatedUpload("synthetic.wav", "audio/wav", ".wav", 12, Path("unused.wav"))
        with tempfile.TemporaryDirectory() as temporary, patch.dict("os.environ", {"UPLOAD_TMP_DIR": temporary}), \
             patch("app.services.local_audio_pipeline.decode_audio_file", decode), \
             patch("app.services.local_audio_pipeline._read_audio", return_value=[]):
            try:
                return service.transcribe(upload)
            finally:
                self.assertTrue(folders)
                self.assertFalse(any(folder.exists() for folder in folders))

    def test_partial_failure_keeps_other_ranges_and_deletes_decoded_audio(self):
        result = self._run_fake(failures=(1,))
        self.assertEqual("partial", result.status)
        self.assertEqual([(120, 240)], [(r.start, r.end) for r in result.failed_ranges])
        self.assertEqual(2, len(result.raw_segments))
        self.assertTrue(result.requires_review)

    def test_diarization_failure_preserves_asr_and_cleanup(self):
        result = self._run_fake(diar_failure=True)
        self.assertEqual("fallback", result.diarization_status)
        self.assertEqual(3, len(result.raw_segments))
        self.assertIn("diarization_failed", result.error_codes)
        self.assertTrue(all(s.speaker is None for s in result.segments))

    def test_gpu_oom_retains_prior_asr_and_reports_unprocessed_ranges(self):
        result = self._run_fake(failures=(1,), failure_message="CUDA out of memory")
        self.assertEqual("partial", result.status)
        self.assertEqual(1, len(result.raw_segments))
        self.assertEqual([(120, 240, "gpu_oom"), (240, 245, "not_processed")],
                         [(r.start, r.end, r.code) for r in result.failed_ranges])
        self.assertIn("gpu_oom", result.error_codes)
        diar = self._run_fake(diar_failure=True, failure_message="CUDA out of memory")
        self.assertEqual("fallback", diar.diarization_status)
        self.assertEqual(3, len(diar.raw_segments))
        self.assertIn("gpu_oom", diar.error_codes)
        self.assertTrue(any("GPU" in warning for warning in diar.warnings))

    def test_no_speech_and_total_failure_both_cleanup(self):
        with self.assertRaises(AudioNoSpeechDetectedError):
            self._run_fake(no_speech=True)
        with self.assertRaises(AudioTranscriptionRuntimeError):
            self._run_fake(failures=(0, 1, 2))


class AudioRouteLifecycleTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[require_preview_access] = lambda: "synthetic-actor"
        self.client = TestClient(app)

    @staticmethod
    def wav():
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(b"\0" * 3200)
        return buffer.getvalue()

    def test_upload_cleanup_success_asr_oom_diar_fallback_and_limits(self):
        for failure in (None, AudioTranscriptionRuntimeError("GPU 메모리가 부족합니다."), AudioDurationLimitError("duration"), AudioNoSpeechDetectedError("no speech")):
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as directory:
                seen = []
                def transcribe(upload, **kwargs):
                    seen.append(upload.temp_path)
                    self.assertTrue(upload.temp_path.exists())
                    if failure:
                        raise failure
                    from app.schemas.audio import AudioTranscriptionResponse
                    return AudioTranscriptionResponse(transcription_id="synthetic", filename="synthetic.wav", runtime_mode="real", transcript_text="안 갔다", diarization_status="fallback")
                service = type("Service", (), {"transcribe": staticmethod(transcribe)})()
                with patch.dict("os.environ", {"UPLOAD_TMP_DIR": directory}), patch("app.api.routes.audio.get_transcription_service", return_value=service):
                    response = self.client.post("/api/audio/transcribe", files={"file": ("synthetic.wav", self.wav(), "audio/wav")})
                self.assertEqual(200 if failure is None else 500 if isinstance(failure, AudioTranscriptionRuntimeError) else 422, response.status_code)
                self.assertTrue(seen)
                self.assertFalse(any(path.exists() for path in seen))
                self.assertEqual([], list(Path(directory).iterdir()))

    def test_privacy_proposal_is_local_and_preserves_negation(self):
        response = self.client.post("/api/audio/deidentify", json={"text": "안 갔다. 친구 김하린에게 synth@example.org로 연락했다."})
        self.assertEqual(200, response.status_code)
        self.assertEqual("no-store", response.headers["cache-control"])
        self.assertIn("안 갔다", response.json()["text"])
        # The current main detector does not recognize this unlabeled name.
        # Keep that limitation explicit; the counselor must review the proposal.
        self.assertIn("김하린", response.json()["text"])
        self.assertNotIn("synth@example.org", response.json()["text"])
        self.assertTrue(response.json()["requires_confirmation"])

    def test_translation_and_other_languages_are_rejected(self):
        for data in ({"task": "translate"}, {"language": "en"}, {"expected_speakers": "0"}):
            response = self.client.post("/api/audio/transcribe", files={"file": ("synthetic.wav", self.wav(), "audio/wav")}, data=data)
            self.assertEqual(422, response.status_code)


if __name__ == "__main__":
    unittest.main()
