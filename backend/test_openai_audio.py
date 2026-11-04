"""Hosted audio contract, authentication, consent and temporary-file regressions."""
import base64
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import wave

from fastapi.testclient import TestClient
from app.api.security import require_preview_access
from app.services.openai_audio import validate_references
from app.services.upload_validation import UploadValidationError


def wav(seconds=3):
    data = io.BytesIO()
    with wave.open(data, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b'\0\0' * int(seconds * 16000))
    return data.getvalue()


class HostedAudioTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('audio_wrapper_test',
            Path(__file__).resolve().parents[1] / 'api/materials/documents/extract.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.app = module.app
        self.app.dependency_overrides[require_preview_access] = lambda: 'synthetic-user'
        self.client = TestClient(self.app)
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'AUDIO_TRANSCRIPTION_ENGINE': 'openai',
            'AUDIO_TRANSCRIPTION_STUB': '0', 'ENABLE_AUDIO_TRANSCRIPTION': '1',
            'OPENAI_API_KEY': 'synthetic-test-not-a-key', 'UPLOAD_TMP_DIR': self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.app.dependency_overrides.clear()
        self.tmp.cleanup()

    def post(self, **data):
        return self.client.post('/api/materials/documents/extract?audio_path=transcribe',
            files={'file': ('synthetic.wav', wav(), 'audio/wav')}, data=data)

    def test_capability_and_consent_guard(self):
        result = self.client.get('/api/materials/documents/extract?audio_path=capabilities')
        self.assertEqual('openai', result.json()['provider'])
        with patch('openai.OpenAI') as provider:
            self.assertEqual(422, self.post().status_code)
            provider.assert_not_called()
        self.assertEqual([], list(Path(self.tmp.name).iterdir()))

    def test_provider_result_and_cleanup_preserve_raw_text(self):
        payload = {'segments': [{'start': 0, 'end': 2.5, 'speaker': 'A', 'text': '안 갔다. 3회기.'}]}
        provider = MagicMock()
        provider.return_value.__enter__.return_value.audio.transcriptions.create.return_value.model_dump.return_value = payload
        with patch('openai.OpenAI', provider):
            response = self.post(cloud_audio_consent='true')
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual('안 갔다. 3회기.', response.json()['raw_segments'][0]['text'])
        self.assertEqual('A', response.json()['segments'][0]['speaker'])
        self.assertEqual('no-store', response.headers['cache-control'])
        self.assertEqual([], list(Path(self.tmp.name).iterdir()))
        self.assertEqual('https://api.openai.com/v1', provider.call_args.kwargs['base_url'])

    def test_provider_failure_cleans_temp_and_redacts_body(self):
        from openai import APIConnectionError
        import httpx
        provider = MagicMock()
        provider.return_value.__enter__.return_value.audio.transcriptions.create.side_effect = APIConnectionError(
            message='private synthetic provider payload', request=httpx.Request('POST', 'https://api.openai.com/v1/audio/transcriptions'))
        with patch('openai.OpenAI', provider):
            response = self.post(cloud_audio_consent='true')
        self.assertEqual(500, response.status_code)
        self.assertNotIn('private synthetic', response.text)
        self.assertEqual([], list(Path(self.tmp.name).iterdir()))

    def test_partial_diarization_retains_text(self):
        provider = MagicMock()
        provider.return_value.__enter__.return_value.audio.transcriptions.create.return_value.model_dump.return_value = {'text': '안 갔다.'}
        with patch('openai.OpenAI', provider):
            response = self.post(cloud_audio_consent='true')
        self.assertEqual('fallback', response.json()['diarization_status'])
        self.assertIsNone(response.json()['segments'][0]['speaker'])

    def test_silent_chunk_is_reviewable_without_asr_failure(self):
        provider = MagicMock()
        provider.return_value.__enter__.return_value.audio.transcriptions.create.return_value.model_dump.return_value = {'text': '', 'segments': []}
        with patch('openai.OpenAI', provider):
            response = self.post(cloud_audio_consent='true')
        self.assertEqual(200, response.status_code)
        self.assertEqual(['no_speech'], response.json()['error_codes'])
        self.assertEqual([], response.json()['segments'])
        self.assertEqual([], list(Path(self.tmp.name).iterdir()))

    def test_reference_rejects_remote_url_and_oversized_duration(self):
        for refs in [[{'name': 'speaker_0', 'audio': 'https://example.com/secret.wav'}],
                     [{'name': 'speaker_0', 'audio': 'data:audio/wav;base64,' + base64.b64encode(wav(5)).decode()}], {}]:
            with self.assertRaises(UploadValidationError):
                validate_references(refs)
        valid = [{'name': 'speaker_0', 'audio': 'data:audio/wav;base64,' + base64.b64encode(wav()).decode()}]
        self.assertEqual(['speaker_0'], validate_references(valid)[0])

    def test_privacy_preserves_medication_names_and_masks_identity_label(self):
        text = '약 이름은 에스시탈로프람이라고 들었어요. 약 이름: 리튬. 이름: 윤다온, 안 갔다.'
        response = self.client.post('/api/audio/deidentify', json={'text': text})
        self.assertEqual(200, response.status_code)
        masked = response.json()['text']
        self.assertIn('에스시탈로프람', masked)
        self.assertIn('약 이름: 리튬', masked)
        self.assertNotIn('윤다온', masked)
        self.assertIn('안 갔다', masked)

    def test_unauthenticated_upload_never_calls_provider(self):
        from app.core.config import settings
        self.app.dependency_overrides.clear()
        with patch.object(settings, 'enable_real_user_auth', True), patch.object(settings, 'runtime_environment', 'production'), \
             patch.object(settings, 'remind_allow_local_bypass', False), patch('openai.OpenAI') as provider:
            self.assertEqual(401, self.post(cloud_audio_consent='true').status_code)
            provider.assert_not_called()


if __name__ == '__main__':
    unittest.main()
