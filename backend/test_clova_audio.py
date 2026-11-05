"""Synthetic CLOVA contract and privacy boundary regressions; no live API calls."""
import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import wave

import httpx
from fastapi.testclient import TestClient
from app.api.security import require_preview_access


def wav(seconds=3):
    data = io.BytesIO()
    with wave.open(data, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b'\0\0' * int(seconds * 16000))
    return data.getvalue()


def segment(start, end, label='1', text='안 갔다. 3회기.', words=None, confidence=0.95):
    return dict(start=start, end=end, text=text, diarization={'label': label},
                confidence=confidence, words=words or [])


def refs(count=2):
    return [{'name': f'speaker_{i}', 'audio': 'data:audio/wav;base64,' + base64.b64encode(wav()).decode()}
            for i in range(count)]


class ClovaAudioTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('clova_wrapper_test',
            Path(__file__).resolve().parents[1] / 'api/materials/documents/extract.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.app = module.app
        self.app.dependency_overrides[require_preview_access] = lambda: 'synthetic-user'
        self.client = TestClient(self.app)
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'AUDIO_TRANSCRIPTION_ENGINE': 'clova',
            'AUDIO_TRANSCRIPTION_STUB': '0', 'ENABLE_AUDIO_TRANSCRIPTION': '1',
            'CLOVA_SPEECH_SECRET_KEY': 'synthetic-not-a-key',
            'CLOVA_SPEECH_INVOKE_URL': 'https://clovaspeech-gw.ncloud.com/external/v1/1/synthetic',
            'CLOVA_SPEECH_KEYWORDS': '', 'UPLOAD_TMP_DIR': self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.app.dependency_overrides.clear()
        self.tmp.cleanup()

    def post(self, **data):
        fields = {'cloud_audio_consent': 'true', 'cloud_audio_provider': 'clova'}
        fields.update(data)
        return self.client.post('/api/materials/documents/extract?audio_path=transcribe',
            files={'file': ('synthetic.wav', wav(), 'audio/wav')}, data=fields)

    def provider(self, payload=None):
        response = httpx.Response(200, json=payload or {'result': 'COMPLETED', 'segments': [segment(0, 2500)]},
            request=httpx.Request('POST', 'https://clovaspeech-gw.ncloud.com'))
        provider = MagicMock()
        provider.return_value.__enter__.return_value.post.return_value = response
        return provider

    def test_capabilities_and_missing_config_never_fall_back_to_openai(self):
        capabilities = self.client.get('/api/audio/capabilities').json()
        self.assertEqual('clova', capabilities['provider'])
        self.assertIsNone(capabilities['max_duration_seconds'])
        self.assertEqual(60, capabilities['chunk_seconds'])
        with patch.dict(os.environ, {'CLOVA_SPEECH_SECRET_KEY': ''}), patch('openai.OpenAI') as other:
            self.assertFalse(self.client.get('/api/audio/capabilities').json()['transcription']['available'])
            self.assertEqual(503, self.post().status_code)
            other.assert_not_called()
        self.assertEqual([], list(Path(self.tmp.name).iterdir()))

    def test_consent_is_bound_to_provider_before_upload_or_call(self):
        with patch('app.services.clova_audio.httpx.Client') as provider:
            for fields in [{'cloud_audio_consent': 'false'}, {'cloud_audio_provider': 'openai'}, {'cloud_audio_provider': ''}]:
                self.assertEqual(422, self.post(**fields).status_code)
            provider.assert_not_called()
        self.assertEqual([], list(Path(self.tmp.name).iterdir()))

    def test_authenticated_wav_result_preserves_raw_and_milliseconds(self):
        provider = self.provider({'result': 'COMPLETED', 'segments': [segment(200, 2500, words=[[200, 1000, '안 갔다.']])]})
        with patch('app.services.clova_audio.httpx.Client', provider):
            response = self.post(expected_speakers='2')
        self.assertEqual(200, response.status_code, response.text)
        result = response.json()
        self.assertEqual('clova', result['transcription_engine'])
        self.assertEqual('1', result['raw_segments'][0]['speaker'])
        self.assertEqual('clova_1', result['segments'][0]['speaker'])
        self.assertEqual(0.2, result['segments'][0]['start'])
        self.assertEqual('안 갔다. 3회기.', result['transcript_text'])
        params = json.loads(provider.return_value.__enter__.return_value.post.call_args.kwargs['files']['params'][1])
        self.assertEqual('ko-KR', params['language'])
        self.assertEqual(2, params['diarization']['speakerCountMax'])
        self.assertFalse(params['resultToObs'])
        self.assertFalse(provider.call_args.kwargs['follow_redirects'])
        self.assertEqual('no-store', response.headers['cache-control'])
        self.assertEqual([], list(Path(self.tmp.name).iterdir()))

    def test_reference_labels_can_swap_without_swapping_people(self):
        payload = {'result': 'COMPLETED', 'segments': [segment(0, 3000, '2', '참조 0'),
            segment(3500, 6500, '1', '참조 1'), segment(7100, 8000, '1'), segment(8100, 9500, '2')]}
        provider = self.provider(payload)
        with patch('app.services.clova_audio.httpx.Client', provider):
            result = self.post(speaker_references=json.dumps(refs())).json()
        self.assertEqual(['speaker_1', 'speaker_0'], [s['speaker'] for s in result['segments']])
        self.assertAlmostEqual(0.1, result['segments'][0]['start'])
        self.assertNotIn('참조', result['transcript_text'])
        self.assertEqual(7, result['stage_metrics']['reference_seconds'])

    def test_conflicting_reference_identity_remains_unmatched(self):
        payload = {'result': 'COMPLETED', 'segments': [segment(0, 3000, '1'),
            segment(3500, 6500, '1'), segment(7100, 9000, '1')]}
        with patch('app.services.clova_audio.httpx.Client', self.provider(payload)):
            result = self.post(speaker_references=json.dumps(refs())).json()
        self.assertEqual('fallback', result['diarization_status'])
        self.assertIn('speaker_reference_unmatched', result['segments'][0]['review_flags'])
        self.assertEqual('unmatched_1', result['segments'][0]['speaker'])

    def test_reference_text_is_removed_when_segment_crosses_content_boundary(self):
        payload = {'result': 'COMPLETED', 'segments': [segment(0, 3000, '1'),
            segment(3200, 5000, '1', '참조 단어 안 갔다.', [[3200, 3400, '참조'], [3600, 4900, '안 갔다.']])]}
        with patch('app.services.clova_audio.httpx.Client', self.provider(payload)):
            result = self.post(speaker_references=json.dumps(refs(1))).json()
        self.assertEqual('안 갔다.', result['transcript_text'])
        self.assertIn('reference_boundary', result['segments'][0]['review_flags'])
        self.assertAlmostEqual(0.1, result['segments'][0]['words'][0]['start'])

    def test_missing_alignment_never_injects_reference_text(self):
        payload = {'result': 'COMPLETED', 'segments': [segment(3200, 5000, '1', '참조 단어와 본문'), segment(5100, 6000, '1')]}
        with patch('app.services.clova_audio.httpx.Client', self.provider(payload)):
            result = self.post(speaker_references=json.dumps(refs(1))).json()
        self.assertEqual('partial', result['status'])
        self.assertEqual('안 갔다. 3회기.', result['transcript_text'])
        self.assertEqual('timestamp_unavailable', result['failed_ranges'][0]['code'])

    def test_silence_after_references_is_not_hallucinated_into_transcript(self):
        payload = {'result': 'COMPLETED', 'segments': [segment(0, 3000, '1', '참조')], 'text': '참조'}
        with patch('app.services.clova_audio.httpx.Client', self.provider(payload)):
            result = self.post(speaker_references=json.dumps(refs(1))).json()
        self.assertEqual(['no_speech'], result['error_codes'])
        self.assertEqual([], result['segments'])

    def test_low_confidence_and_absent_speaker_retain_text_for_review(self):
        with patch('app.services.clova_audio.httpx.Client', self.provider({'result': 'COMPLETED',
                'segments': [segment(0, 2500, None, confidence=0.5)]})):
            result = self.post().json()
        self.assertEqual('fallback', result['diarization_status'])
        self.assertIn('low_confidence', result['segments'][0]['review_flags'])
        self.assertEqual('안 갔다. 3회기.', result['transcript_text'])

    def test_provider_error_redaction_and_cleanup(self):
        provider = self.provider()
        provider.return_value.__enter__.return_value.post.side_effect = httpx.ReadTimeout('private-secret-body')
        with patch('app.services.clova_audio.httpx.Client', provider):
            response = self.post()
        self.assertEqual(500, response.status_code)
        self.assertNotIn('private-secret', response.text)
        self.assertEqual([], list(Path(self.tmp.name).iterdir()))

    def test_rejects_malicious_endpoint_reference_and_malformed_response(self):
        with patch.dict(os.environ, {'CLOVA_SPEECH_INVOKE_URL': 'https://attacker.invalid/path'}), \
             patch('app.services.clova_audio.httpx.Client') as provider:
            self.assertEqual(503, self.post().status_code)
            provider.assert_not_called()
        with patch('app.services.clova_audio.httpx.Client') as provider:
            self.assertEqual(422, self.post(speaker_references=json.dumps([{'name': 'speaker_0', 'audio': 'https://attacker.invalid/x.wav'}])).status_code)
            provider.assert_not_called()
        for payload in [{'result': 'FAILED', 'message': 'private detail'}, {'result': 'SUCCEEDED'},
                        {'result': 'COMPLETED', 'segments': [segment(-1, 1000)]},
                        {'result': 'COMPLETED', 'segments': [segment(3100, 3500)]}]:
            with patch('app.services.clova_audio.httpx.Client', self.provider(payload)):
                response = self.post()
            self.assertEqual(500, response.status_code)
            self.assertNotIn('private detail', response.text)
        self.assertEqual([], list(Path(self.tmp.name).iterdir()))

    def test_unauthenticated_upload_never_calls_provider(self):
        from app.core.config import settings
        self.app.dependency_overrides.clear()
        with patch.object(settings, 'enable_real_user_auth', True), patch.object(settings, 'runtime_environment', 'production'), \
             patch.object(settings, 'remind_allow_local_bypass', False), patch('app.services.clova_audio.httpx.Client') as provider:
            self.assertEqual(401, self.post().status_code)
            provider.assert_not_called()


if __name__ == '__main__':
    unittest.main()
