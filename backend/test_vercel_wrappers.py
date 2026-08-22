"""Regression tests for Vercel serverless API wrappers."""
from __future__ import annotations

import sys
from pathlib import Path
import unittest
import unittest.mock

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
from api.documents.export import app as export_app
from api.documents.capabilities import app as capabilities_app

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
        self.orig_supabase_url = settings.supabase_url
        self.orig_supabase_role_key = settings.supabase_service_role_key

        # Configure for strict preview validation
        settings.runtime_environment = "production"
        settings.remind_allow_local_bypass = False
        settings.remind_preview_api_token = "secret-test-token"
        settings.use_stub = True  # force stub logic to avoid external OpenAI calls
        settings.enable_persistence = False
        settings.enable_case_memory = False
        settings.supabase_url = None
        settings.supabase_service_role_key = None

    def tearDown(self):
        # Restore settings
        settings.runtime_environment = self.orig_env
        settings.remind_allow_local_bypass = self.orig_bypass
        settings.remind_preview_api_token = self.orig_token
        settings.use_stub = self.orig_use_stub
        settings.enable_persistence = self.orig_persistence
        settings.enable_case_memory = self.orig_case_memory
        settings.supabase_url = self.orig_supabase_url
        settings.supabase_service_role_key = self.orig_supabase_role_key

    def test_generate_endpoint_requires_token(self):
        client = TestClient(generate_app)
        payload = {
            "case_id": "CASE-MUSPSY-1416",
            "session_number": 5,
            "session_date": "2026.04.28",
            "counselor_name": "데모 상담사",
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

        # 2. Valid token but persistence disabled -> 409
        response = client.post("/", json=payload, headers={"X-Remind-Preview-Token": "secret-test-token"})
        self.assertEqual(response.status_code, 409)
        self.assertIn("ENABLE_PERSISTENCE is false", response.json()["detail"])

    @unittest.mock.patch("app.services.supabase_storage.storage")
    def test_confirm_endpoint_success_with_mock_persistence(self, mock_storage):
        orig_persistence = settings.enable_persistence
        orig_supabase_url = settings.supabase_url
        orig_supabase_key = settings.supabase_service_role_key
        orig_case_memory = settings.enable_case_memory
        try:
            settings.enable_persistence = True
            settings.supabase_url = "https://mock.supabase.co"
            settings.supabase_service_role_key = "mock-key"
            settings.enable_case_memory = False

            note_data = {
                "id": "test-note-id",
                "case_id": "test-case-id",
                "session_id": "test-session-id",
                "note_type": "session_note",
                "draft_json": {},
                "confirmed_json": {},
                "confirmation_status": "draft",
                "confirmed_by": None,
                "created_at": "2026-07-23",
            }
            session_data = {
                "id": "test-session-id",
                "case_id": "test-case-id",
                "session_number": 5,
                "session_date": "2026-07-23",
                "session_title": "session-title",
            }
            case_data = {
                "id": "test-case-id",
                "case_alias": "alias",
                "counselor_id": "preview_server_actor",
                "status": "active",
            }

            def mock_maybe_single(table, query):
                if table == "generated_notes":
                    return note_data
                elif table == "sessions":
                    return session_data
                elif table == "cases":
                    return case_data
                return None

            mock_storage.maybe_single.side_effect = mock_maybe_single
            mock_storage.persistence_enabled = True
            mock_storage.configured = True

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
                "create_case_memory": False,
            }

            response = client.post("/", json=payload, headers={"X-Remind-Preview-Token": "secret-test-token"})
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["note_id"], "test-note-id")
            self.assertEqual(data["confirmation_status"], "confirmed")
            mock_storage.update.assert_called()
        finally:
            settings.enable_persistence = orig_persistence
            settings.supabase_url = orig_supabase_url
            settings.supabase_service_role_key = orig_supabase_key
            settings.enable_case_memory = orig_case_memory

    @unittest.mock.patch("app.services.retrieval.storage")
    def test_retrieve_document_template_logic(self, mock_storage):
        orig_enable_rag = settings.enable_rag
        try:
            settings.enable_rag = True
            mock_storage.retrieval_enabled = True

            documents_data = [
                {
                    "id": "doc-uuid-1",
                    "title": "Re:mind session note template checklist",
                    "source_type": "session_note",
                    "doc_category": "session_note_template",
                    "authority_level": "professional_association_public_template",
                }
            ]
            chunks_data = [
                {
                    "id": "chunk-uuid-1",
                    "document_id": "doc-uuid-1",
                    "chunk_text": "session_metadata",
                    "chunk_type": "required_field",
                    "metadata_json": {
                        "required_fields": ["session_metadata", "case_id", "session_number", "session_date"]
                    }
                }
            ]

            selected_queries = []
            def mock_select(table, query):
                selected_queries.append((table, query))
                if table == "kb_documents":
                    return documents_data
                elif table == "kb_chunks":
                    return chunks_data
                return []

            mock_storage.select.side_effect = mock_select

            from app.services.retrieval import retrieve_document_template
            context = retrieve_document_template("session_note")

            doc_query = next(q for t, q in selected_queries if t == "kb_documents")
            self.assertIn("session_note_template", doc_query["doc_category"])
            self.assertIsNotNone(context)
            self.assertTrue(len(context.required_fields) > 0)
            self.assertIn("session_metadata", context.required_fields)
            self.assertTrue(any(ref.startswith("kb_template:") for ref in context.source_refs))
        finally:
            settings.enable_rag = orig_enable_rag

    def test_recompose_endpoint_requires_token(self):
        client = TestClient(recompose_app)
        payload = {
            "session_input": {
                "case_id": "CASE-MUSPSY-1416",
                "session_number": 5,
                "session_date": "2026.04.28",
                "counselor_name": "데모 상담사",
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

    def test_capabilities_endpoint_requires_token(self):
        client = TestClient(capabilities_app)
        response = client.get("/")
        self.assertEqual(response.status_code, 401)

        response = client.get("/", headers={"X-Remind-Preview-Token": "secret-test-token"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["docx"]["available"])

    def test_export_endpoint_requires_token(self):
        client = TestClient(export_app)
        payload = {
            "format": "docx",
            "document_type": "session_note",
            "case_id": "test-case-id",
            "session_number": 5,
            "session_date": "2026-07-23",
            "title": "test title",
            "metadata": {},
            "sections": [
                {
                    "id": "sec-1",
                    "title": "sec title",
                    "content": "sec content"
                }
            ]
        }
        response = client.post("/", json=payload)
        self.assertEqual(response.status_code, 401)

        response = client.post("/", json=payload, headers={"X-Remind-Preview-Token": "secret-test-token"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


if __name__ == "__main__":
    unittest.main()
