"""Offline integration checks for the main-based audio-only entry point."""
from pathlib import Path
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.security import require_preview_access
from app.audio_main import app, allowed_origins
from app.core.config import settings
from app.services.local_audio_pipeline import LocalAudioConfig


class AudioAppBoundaryTests(unittest.TestCase):
    def tearDown(self):
        app.dependency_overrides.clear()

    def test_audio_routes_require_existing_auth_without_loading_models(self):
        with patch.object(settings, 'enable_real_user_auth', True), \
             patch.object(settings, 'runtime_environment', 'production'), \
             patch.object(settings, 'remind_allow_local_bypass', False), \
             patch('app.api.routes.audio.get_transcription_service') as factory:
            client = TestClient(app)
            self.assertEqual(401, client.get('/api/audio/capabilities').status_code)
            self.assertEqual(401, client.post('/api/audio/deidentify', json={'text': 'synthetic'}).status_code)
            self.assertEqual(404, client.post('/api/notes/generate', json={}).status_code)
            factory.assert_not_called()

    def test_local_review_does_not_call_model_backed_main_detector(self):
        app.dependency_overrides[require_preview_access] = lambda: 'synthetic-actor'
        with patch('app.services.storage_deidentification._extract_entities', side_effect=AssertionError('external detector called')) as detector, \
             patch('app.services.llm.get_structured_llm', side_effect=AssertionError('LLM called')) as provider:
            response = TestClient(app).post('/api/audio/deidentify', json={'text': '안 갔다. synthetic@example.org'})
            self.assertEqual(200, response.status_code)
            self.assertIn('안 갔다', response.json()['text'])
            self.assertNotIn('synthetic@example.org', response.json()['text'])
            self.assertTrue(response.json()['requires_confirmation'])
            self.assertEqual('no-store', response.headers['cache-control'])
            detector.assert_not_called()
            provider.assert_not_called()

    def test_blackwell_template_is_disabled_and_configuration_valid_only(self):
        from dotenv import dotenv_values
        template = Path(__file__).parent / 'audio-blackwell.env.example'
        with patch.dict(os.environ, dotenv_values(template), clear=True):
            config = LocalAudioConfig.from_env()
            self.assertEqual('0', os.environ['ENABLE_AUDIO_TRANSCRIPTION'])
            self.assertEqual(1, config.batch_size)
            self.assertEqual(3600, config.max_duration_seconds)
            self.assertEqual('cuda', config.device)
            self.assertEqual('clips', config.whisper_vad_mode)
            self.assertEqual(os.environ['TMPDIR'], os.environ['UPLOAD_TMP_DIR'])
        with patch.dict(os.environ, {'AUDIO_ALLOWED_ORIGINS': 'http://untrusted.example'}):
            with self.assertRaises(ValueError):
                allowed_origins()


if __name__ == '__main__':
    unittest.main()
