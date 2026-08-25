"""Regression tests for Vercel serverless API wrappers."""
from __future__ import annotations

import sys
import io
import json
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
from api.notes.draft import app as draft_detail_app
from api.notes.confirm import app as confirm_app
from api.documents.export import app as export_app
from api.documents.capabilities import app as capabilities_app
material_extract_app = importlib.import_module("api.materials.documents.extract").app

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
        self.orig_supabase_service_key = settings.supabase_service_key
        self.orig_supabase_anon_key = settings.supabase_anon_key
        self.orig_real_user_auth = settings.enable_real_user_auth
        self.orig_legacy_preview_token = settings.allow_legacy_preview_token
        self.orig_supabase_publishable_key = settings.supabase_publishable_key

        # Configure for strict preview validation
        settings.runtime_environment = "production"
        settings.remind_allow_local_bypass = False
        settings.remind_preview_api_token = "secret-test-token"
        settings.use_stub = True  # force stub logic to avoid external OpenAI calls
        settings.enable_persistence = False
        settings.enable_case_memory = False
        settings.supabase_url = None
        settings.supabase_service_role_key = None
        settings.supabase_service_key = None
        settings.supabase_anon_key = None
        settings.enable_real_user_auth = False
        settings.allow_legacy_preview_token = True

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
        settings.supabase_service_key = self.orig_supabase_service_key
        settings.supabase_anon_key = self.orig_supabase_anon_key
        settings.enable_real_user_auth = self.orig_real_user_auth
        settings.allow_legacy_preview_token = self.orig_legacy_preview_token
        settings.supabase_publishable_key = self.orig_supabase_publishable_key

    def test_generate_endpoint_requires_token(self):
        client = TestClient(generate_app)
        payload = {
            "case_id": "CASE-SYNTHETIC-001",
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

    def test_api_fails_closed_when_real_auth_is_not_configured(self):
        settings.allow_legacy_preview_token = False
        settings.enable_real_user_auth = False
        client = TestClient(material_extract_app)
        response = client.post(
            "/",
            files={"file": ("session.txt", "safe test", "text/plain")},
            headers={"X-Remind-Preview-Token": "secret-test-token"},
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("사용자 인증", response.json()["detail"])

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
                "case_id": "CASE-SYNTHETIC-001",
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

    @unittest.mock.patch("api.notes.draft.get_temporary_draft")
    def test_draft_detail_endpoint_preserves_actor_scope(self, mock_get_draft):
        mock_get_draft.return_value = {
            "draft_id": "draft_test1234",
            "case_id": "CASE-SYNTHETIC-001",
            "session_number": 1,
            "saved_at": "2026-08-26T00:00:00+00:00",
        }
        client = TestClient(draft_detail_app)

        self.assertEqual(client.get("/", params={"draft_id": "draft_test1234"}).status_code, 401)
        response = client.get(
            "/",
            params={"draft_id": "draft_test1234"},
            headers={"X-Remind-Preview-Token": "secret-test-token"},
        )

        self.assertEqual(response.status_code, 200)
        mock_get_draft.assert_called_once_with("draft_test1234", actor="preview_server_actor")

        mock_get_draft.reset_mock()
        response = client.get(
            "/api/notes/drafts/draft_test1234",
            headers={"X-Remind-Preview-Token": "secret-test-token"},
        )
        self.assertEqual(response.status_code, 200)
        mock_get_draft.assert_called_once_with("draft_test1234", actor="preview_server_actor")

    def test_vercel_rewrite_routes_draft_detail_to_function(self):
        import json

        config = json.loads((ROOT_DIR / "vercel.json").read_text(encoding="utf-8"))
        self.assertIn(
            {
                "source": "/api/notes/drafts/:draft_id",
                "destination": "/api/notes/draft?draft_id=:draft_id",
            },
            config["rewrites"],
        )

    def test_draft_database_keys_are_scoped_per_user(self):
        from app.services.supabase_store import _scoped_draft_id

        first = _scoped_draft_id("draft_shared", user_id="user-a")
        second = _scoped_draft_id("draft_shared", user_id="user-b")
        self.assertNotEqual(first, second)
        self.assertEqual(first, _scoped_draft_id("draft_shared", user_id="user-a"))

    @unittest.mock.patch("app.services.supabase_store.urlopen")
    def test_draft_storage_uses_user_jwt_for_rls(self, mock_urlopen):
        from app.api.security import AuthenticatedActor
        from app.schemas.note import TemporaryDraftRecord
        from app.services.supabase_store import configured_for, upsert_draft_row

        settings.supabase_url = "https://mock.supabase.co"
        settings.supabase_publishable_key = "public-test-key"
        actor = AuthenticatedActor("user-a", "verified-user-jwt")
        record = TemporaryDraftRecord(
            draft_id="draft_test1234",
            case_id="CASE-SYNTHETIC-001",
            session_number=1,
            saved_at="2026-08-26T00:00:00+00:00",
        )
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = b""
        mock_urlopen.return_value = response

        self.assertTrue(configured_for(actor))
        upsert_draft_row(record, actor=actor)

        request = mock_urlopen.call_args.args[0]
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["apikey"], "public-test-key")
        self.assertEqual(headers["authorization"], "Bearer verified-user-jwt")
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["user_id"], "user-a")

    @unittest.mock.patch("app.services.supabase_storage.urlopen")
    def test_generated_note_storage_uses_user_jwt_for_rls(self, mock_urlopen):
        from app.api.security import AuthenticatedActor
        from app.services.supabase_storage import _storage_for_actor

        settings.supabase_url = "https://mock.supabase.co"
        settings.supabase_publishable_key = "public-test-key"
        settings.supabase_service_role_key = "service-role-test-key"
        actor = AuthenticatedActor("user-a", "verified-user-jwt")
        actor_storage = _storage_for_actor(actor)
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = b""
        mock_urlopen.return_value = response

        self.assertTrue(actor_storage.configured)
        actor_storage.insert(
            "cases",
            [{"id": "case-a", "user_id": str(actor)}],
            return_representation=False,
        )

        request = mock_urlopen.call_args.args[0]
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["apikey"], "public-test-key")
        self.assertEqual(headers["authorization"], "Bearer verified-user-jwt")
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body[0]["user_id"], "user-a")

        settings.supabase_publishable_key = None
        settings.supabase_anon_key = None
        self.assertFalse(_storage_for_actor(actor).configured)

    def test_case_retrieval_rejects_a_guessed_foreign_case_id(self):
        from app.services.retrieval import retrieve_case_context

        class TenantStorage:
            retrieval_enabled = True

            def __init__(self):
                self.queries: list[tuple[str, dict[str, str | int]]] = []
                self.rows = {
                    "sessions": [
                        {
                            "id": "session-b",
                            "case_id": "CASE-SHARED",
                            "user_id": "user-b",
                            "session_number": 1,
                            "session_date": "2026-08-20",
                            "session_title": "foreign session",
                            "created_at": "2026-08-20T00:00:00Z",
                        }
                    ],
                    "generated_notes": [
                        {
                            "id": "note-b",
                            "session_id": "session-b",
                            "user_id": "user-b",
                            "note_type": "session_note",
                            "draft_json": {},
                            "confirmed_json": {"sections": {"session_content": "user-b secret"}},
                            "created_at": "2026-08-20T00:00:00Z",
                        }
                    ],
                    "evidence_items": [
                        {
                            "id": "evidence-b",
                            "session_id": "session-b",
                            "user_id": "user-b",
                            "source_type": "direct",
                            "source_ref": "foreign",
                            "source_text": "user-b evidence",
                            "linked_field": "session_content",
                            "created_at": "2026-08-20T00:00:00Z",
                        }
                    ],
                }

            def select(self, table: str, query: dict[str, str | int]):
                self.queries.append((table, dict(query)))
                rows = list(self.rows.get(table, []))
                for field in ("case_id", "user_id"):
                    condition = str(query.get(field) or "")
                    if condition.startswith("eq."):
                        rows = [row for row in rows if row.get(field) == condition[3:]]
                session_condition = str(query.get("session_id") or "")
                if session_condition.startswith("in.(") and session_condition.endswith(")"):
                    allowed = set(session_condition[4:-1].split(","))
                    rows = [row for row in rows if row.get("session_id") in allowed]
                return rows

        fake_storage = TenantStorage()
        original_enable_rag = settings.enable_rag
        try:
            settings.enable_rag = True
            leaked = retrieve_case_context(
                "CASE-SHARED",
                user_id="user-a",
                storage_client=fake_storage,  # type: ignore[arg-type]
            )
            self.assertEqual(leaked, [])

            owned = retrieve_case_context(
                "CASE-SHARED",
                user_id="user-b",
                storage_client=fake_storage,  # type: ignore[arg-type]
            )
            self.assertEqual(len(owned), 1)
            self.assertEqual(owned[0].summary, "user-b secret")
            self.assertTrue(fake_storage.queries)
            self.assertTrue(all("user_id" in query for _table, query in fake_storage.queries))
        finally:
            settings.enable_rag = original_enable_rag

    def test_recompose_cache_is_scoped_by_actor(self):
        from app.schemas.note import RecomposeNoteRequest, SessionInput
        from app.services.recompose_cache import build_recompose_cache_key

        request = RecomposeNoteRequest(
            session_input=SessionInput(
                case_id="CASE-SHARED",
                session_number=1,
                session_date="2026-08-20",
                counselor_name="test counselor",
                counselor_memo="synthetic memo",
                transcript_text="synthetic transcript",
                target_document_type="session_note",
            ),
            visible_section_ids=["session_content"],
        )
        self.assertNotEqual(
            build_recompose_cache_key(request, actor="user-a"),
            build_recompose_cache_key(request, actor="user-b"),
        )

    def test_capabilities_endpoint_requires_token(self):
        client = TestClient(capabilities_app)
        response = client.get("/")
        self.assertEqual(response.status_code, 401)

        response = client.get("/", headers={"X-Remind-Preview-Token": "secret-test-token"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["docx"]["available"])

    def test_material_extract_endpoint_requires_token_and_extracts_txt(self):
        client = TestClient(material_extract_app)
        files = {"file": ("session.txt", "상담사가 입력한 테스트 문장입니다.", "text/plain")}

        response = client.post("/", files=files)
        self.assertEqual(response.status_code, 401)

        response = client.post(
            "/",
            files=files,
            headers={"X-Remind-Preview-Token": "secret-test-token"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("테스트 문장", response.json()["extracted_text"])
        self.assertEqual(response.headers["cache-control"], "no-store")

    @unittest.mock.patch("app.api.security.urlopen")
    def test_material_extract_uses_supabase_bearer_identity(self, mock_urlopen):
        settings.enable_real_user_auth = True
        settings.supabase_url = "https://mock.supabase.co"
        settings.supabase_publishable_key = "mock-publishable-key"

        auth_response = unittest.mock.MagicMock()
        auth_response.__enter__.return_value.read.return_value = b'{"id":"user-a"}'
        mock_urlopen.return_value = auth_response

        client = TestClient(material_extract_app)
        files = {"file": ("session.txt", io.BytesIO(b"safe test content"), "text/plain")}
        self.assertEqual(client.post("/", files=files).status_code, 401)

        files = {"file": ("session.txt", io.BytesIO(b"safe test content"), "text/plain")}
        response = client.post("/", files=files, headers={"Authorization": "Bearer valid-user-token"})
        self.assertEqual(response.status_code, 200)
        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer valid-user-token")

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
