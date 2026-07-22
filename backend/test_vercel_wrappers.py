"""Regression tests for Vercel serverless API wrappers."""
from __future__ import annotations

import sys
from pathlib import Path
import unittest

from fastapi.testclient import TestClient

# Ensure backend and root are in sys.path
BACKEND_DIR = Path(__file__).resolve().parent
ROOT_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import importlib

# Import wrappers
from api.notes.generate import app as generate_app
from api.notes.recompose import app as recompose_app
supervision_app = importlib.import_module("api.notes.supervision-report").app
from api.notes.drafts import app as drafts_app
from api.notes.confirm import app as confirm_app

from app.core.config import settings


class TestVercelWrappers(unittest.TestCase):
    def setUp(self):
        # Backup original settings
        self.orig_env = settings.runtime_environment
        self.orig_bypass = settings.remind_allow_local_bypass
        self.orig_token = settings.remind_preview_api_token
        self.orig_use_stub = settings.use_stub
        self.orig_persistence = settings.enable_persistence
        self.orig_case_memory = settings.enable_case_memory

        # Configure for strict preview validation
        settings.runtime_environment = "production"
        settings.remind_allow_local_bypass = False
        settings.remind_preview_api_token = "secret-test-token"
        settings.use_stub = True  # force stub logic to avoid external OpenAI calls
        settings.enable_persistence = False
        settings.enable_case_memory = False

    def tearDown(self):
        # Restore settings
        settings.runtime_environment = self.orig_env
        settings.remind_allow_local_bypass = self.orig_bypass
        settings.remind_preview_api_token = self.orig_token
        settings.use_stub = self.orig_use_stub
        settings.enable_persistence = self.orig_persistence
        settings.enable_case_memory = self.orig_case_memory

    def test_generate_endpoint_requires_token(self):
        client = TestClient(generate_app)
        payload = {
            "case_id": "CASE-MUSPSY-1416",
            "session_number": 5,
            "session_date": "2026.04.28",
            "counselor_name": "이수진",
            "counselor_memo": "메모",
            "transcript_text": "축어록",
            "previous_session_summary": "이전 요약",
            "target_document_type": "session_note",
            "persist": False,
        }

        # 1. No token -> 401
        response = client.post("/", json=payload)
        self.assertEqual(response.status_code, 401)

        # 2. Invalid token -> 401
        response = client.post("/", json=payload, headers={"X-Remind-Preview-Token": "bad-token"})
        self.assertEqual(response.status_code, 401)

        # 3. Valid token -> 200
        response = client.post("/", json=payload, headers={"X-Remind-Preview-Token": "secret-test-token"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("session_summary_draft", data)
        self.assertEqual(data["stub"], True)

    def test_confirm_endpoint_requires_token(self):
        client = TestClient(confirm_app)
        payload = {
            "note_id": "test-note-id",
            "confirmed_note": {
                "session_theme": "테마",
                "presenting_problem": "문제",
                "session_content": "내용",
                "counselor_intervention": "개입",
                "client_response": "반응",
                "reflection": "성찰",
                "next_plan": "계획",
            },
            "counselor_edited": True,
            "create_case_memory": True,
        }

        # 1. No token -> 401
        response = client.post("/", json=payload)
        self.assertEqual(response.status_code, 401)

        # 2. Valid token but note_id not found -> 400 or 500 (since persistence is off and stub db doesn't exist)
        # However, it should NOT return 401. Let's verify it gets past the preview token guard.
        response = client.post("/", json=payload, headers={"X-Remind-Preview-Token": "secret-test-token"})
        self.assertNotEqual(response.status_code, 401)

    def test_recompose_endpoint_requires_token(self):
        client = TestClient(recompose_app)
        payload = {
            "session_input": {
                "case_id": "CASE-MUSPSY-1416",
                "session_number": 5,
                "session_date": "2026.04.28",
                "counselor_name": "이수진",
                "counselor_memo": "메모",
                "transcript_text": "축어록",
                "previous_session_summary": "이전 요약",
                "target_document_type": "session_note",
                "persist": False,
            },
            "session_topic": "주제",
            "visible_section_ids": ["session_theme", "presenting_problem"]
        }

        response = client.post("/", json=payload)
        self.assertEqual(response.status_code, 401)

        response = client.post("/", json=payload, headers={"X-Remind-Preview-Token": "secret-test-token"})
        self.assertEqual(response.status_code, 200)

    def test_drafts_endpoint_requires_token(self):
        client = TestClient(drafts_app)

        # List drafts
        response = client.get("/")
        self.assertEqual(response.status_code, 401)

        response = client.get("/", headers={"X-Remind-Preview-Token": "secret-test-token"})
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
