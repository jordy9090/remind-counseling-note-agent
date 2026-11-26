"""Offline API contracts; real registry/role behavior is covered by disposable SQL."""
import io
import json
import os
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

if os.environ.get("REMIND_POC_OFFLINE") != "1":
    raise unittest.SkipTest("Use backend/tests/run_poc_review.py")

from fastapi import HTTPException, Response
from fastapi.testclient import TestClient
from app.api.routes import audio, notes
from app.api.security import AuthenticatedActor, require_preview_access
from app.core.config import settings
from app.main import app
from app.schemas.note import SessionInput, TemporaryDraftSaveRequest
from app.services import deid_review as review, processing_authorization as permission
from app.services import draft_store, supabase_storage
from app.services.qwen_deidentification import Entities
from test_poc_storage import synthetic_result


class ProcessingAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.multiple(settings, poc_mode=True,
            processing_authorization_policy="synthetic-v1", enable_rag=False,
            enable_persistence=True, require_deid_review=True,
            deid_review_signing_key="synthetic-processing-review-" * 3))
        self.actor = AuthenticatedActor("synthetic-A", "synthetic-jwt-A")
        self.allowed = True
        self.calls = []
        self.real_rpc = permission._authorization_rpc
        self.stack.enter_context(patch.object(permission, "_authorization_rpc", side_effect=self.decide))
        self.payload = SessionInput(case_id="synthetic-case-A", session_number=1,
            counselor_memo="SYNTHETIC-PRIVATE-PAYLOAD", transcript_text="", persist=True, insight_lens="none")
        self.detector = self.stack.enter_context(patch.object(review, "detect_entities", return_value=Entities(entities=[])))
        app.dependency_overrides[require_preview_access] = lambda: self.actor
        self.addCleanup(app.dependency_overrides.clear)

    def decide(self, actor, params):
        self.calls.append((str(actor), params.copy()))
        return self.allowed and actor == "synthetic-A" and params["p_case_id"] == "synthetic-case-A"

    def approved(self):
        prepared = review.prepare_review(review.ReviewStart(purpose="generate",
            payload=self.payload.model_dump(mode="json")), self.actor)
        found = review.start_review(review.ReviewStart(purpose="generate", payload=prepared["payload"],
            preparation_token=prepared["preparation_token"]), self.actor)
        return review.confirm_review(review.ReviewConfirm(purpose="generate", payload=found["payload"],
            detection_token=found["detection_token"]), self.actor)

    def test_unconfigured_policy_missing_case_and_shared_actor_fail_closed(self):
        for actor, case_id, policy, status in [(self.actor, "synthetic-case-A", "", 503),
                (self.actor, "", "synthetic-v1", 403), ("shared", "synthetic-case-A", "synthetic-v1", 401)]:
            with self.subTest(status=status), patch.object(settings, "processing_authorization_policy", policy):
                with self.assertRaises(HTTPException) as error:
                    permission.require_case_processing(actor, case_id, "generate", "openai")
                self.assertEqual(status, error.exception.status_code)
        self.assertEqual([], self.calls)

    def test_strict_rpc_result_and_sanitized_failures(self):
        for value in [False, None, "true", 1, {"allowed": True}, [True]]:
            with self.subTest(value=value), patch.object(permission, "_authorization_rpc", return_value=value):
                with self.assertRaises(HTTPException) as error:
                    permission.require_case_processing(self.actor, self.payload.case_id, "generate", "openai")
                self.assertEqual(403, error.exception.status_code)
        with patch.object(permission, "_authorization_rpc", side_effect=RuntimeError("SYNTHETIC-SECRET")):
            with self.assertRaises(HTTPException) as error:
                permission.require_case_processing(self.actor, self.payload.case_id, "generate", "openai")
            self.assertEqual(503, error.exception.status_code)
            self.assertNotIn("SYNTHETIC-SECRET", str(error.exception.detail))
            self.assertTrue(error.exception.__suppress_context__)

    def test_rpc_uses_caller_jwt_and_only_scope_metadata(self):
        # Exercise the real serializer without a service credential or external I/O.
        with patch.multiple(settings, supabase_url="https://synthetic.invalid",
                supabase_publishable_key="synthetic-public", supabase_service_role_key="SYNTHETIC-SERVICE-SECRET"), \
                patch.object(supabase_storage, "urlopen", return_value=io.BytesIO(b"true")) as transport:
            self.assertTrue(self.real_rpc(self.actor, {"p_case_id": self.payload.case_id,
                "p_policy_version": "synthetic-v1", "p_purpose": "generate", "p_provider": "openai"}))
            request = transport.call_args.args[0]
            self.assertEqual("Bearer synthetic-jwt-A", request.headers["Authorization"])
            self.assertEqual("synthetic-public", request.headers["Apikey"])
            self.assertTrue(request.full_url.endswith("/rpc/case_processing_allowed"))
            self.assertNotIn(self.payload.counselor_memo, request.data.decode())

    def test_wrong_owner_case_and_revoked_preparation_never_reach_detector(self):
        for actor, case_id in [(AuthenticatedActor("synthetic-B", "synthetic-jwt-B"), self.payload.case_id),
                (self.actor, "synthetic-case-B")]:
            with self.assertRaises(HTTPException):
                review.prepare_review(review.ReviewStart(purpose="generate", payload=self.payload.model_copy(
                    update={"case_id": case_id}).model_dump(mode="json")), actor)
        prepared = review.prepare_review(review.ReviewStart(purpose="generate",
            payload=self.payload.model_dump(mode="json")), self.actor)
        self.allowed = False
        with self.assertRaises(HTTPException):
            review.start_review(review.ReviewStart(purpose="generate", payload=prepared["payload"],
                preparation_token=prepared["preparation_token"]), self.actor)
        self.detector.assert_not_called()

    def test_revoked_receipt_cannot_generate_or_write(self):
        approved = self.approved()
        self.allowed = False
        with patch.object(notes, "_generate_reviewed") as generate:
            response = TestClient(app).post("/api/notes/generate", json=approved["payload"],
                headers={"X-Review-Receipt": approved["receipt"]})
        self.assertEqual(403, response.status_code)
        generate.assert_not_called()
        with patch.object(draft_store, "_write_to_disk") as disk, \
                patch.object(draft_store.supabase_store, "upsert_draft_row") as store:
            with self.assertRaises(HTTPException):
                draft_store.save_temporary_draft(TemporaryDraftSaveRequest(case_id=self.payload.case_id,
                    session_number=1, form={"counselor_memo": "SYNTHETIC"}), actor=self.actor)
            disk.assert_not_called()
            store.assert_not_called()

    def test_withdrawal_during_generation_blocks_persistence_and_response(self):
        approved = self.approved()
        with patch.object(supabase_storage, "_storage_for_actor") as storage:
            with self.assertRaises(HTTPException):
                with review.reviewed_request("generate", self.payload, approved["receipt"], self.actor):
                    self.allowed = False
                    supabase_storage.persist_generated_note(self.payload, synthetic_result(), actor=self.actor)
            storage.assert_not_called()
        self.allowed = True
        with self.assertRaises(HTTPException):
            with review.reviewed_request("generate", self.payload, approved["receipt"], self.actor):
                self.allowed = False
        self.assertIsNone(permission._scope.get())
        self.assertIsNone(review._approved.get())

    def test_retry_and_egress_recheck_current_permission(self):
        approved = self.approved()
        with self.assertRaises(HTTPException):
            with review.reviewed_request("generate", self.payload, approved["receipt"], self.actor):
                review.require_reviewed_egress()
                self.allowed = False
                review.require_reviewed_egress()
        with self.assertRaises(HTTPException):
            with review.reviewed_request("generate", self.payload, approved["receipt"], self.actor):
                self.fail("Stale retry accepted")
        self.allowed = True
        with review.reviewed_request("generate", self.payload, approved["receipt"], self.actor):
            review.require_reviewed_egress()
        self.assertTrue(all(params["p_policy_version"] == "synthetic-v1" for _, params in self.calls))

    def test_audio_checkbox_cannot_grant_permission(self):
        self.allowed = False
        with patch.object(audio, "current_audio_engine", return_value="clova"), \
                patch.object(audio, "persist_upload_to_temp", AsyncMock()) as upload, \
                patch.object(audio, "get_transcription_service") as provider:
            response = TestClient(app).post("/api/audio/transcribe",
                data={"case_id": self.payload.case_id, "cloud_audio_consent": "true", "cloud_audio_provider": "clova"},
                files={"file": ("synthetic.wav", b"synthetic", "audio/wav")})
            self.assertEqual(403, response.status_code)
            upload.assert_not_called()
            provider.assert_not_called()

    def test_reused_model_cannot_repair_after_withdrawal(self):
        from app.graph import nodes
        approved = self.approved()
        result = synthetic_result()
        state = {name: getattr(result, name) for name in (
            "sanitized_input", "structured_case_data", "evidence_mapped_data")}
        def first_response(*args):
            self.allowed = False
            return result.session_summary_draft
        model = Mock()
        model.invoke.side_effect = first_response
        with patch.multiple(settings, use_stub=False, openai_api_key="synthetic-key"), \
                patch.object(nodes, "get_structured_llm", return_value=model), \
                patch.object(nodes, "summary_quality_issues", return_value={"session_content": "synthetic repair"}):
            with self.assertRaises(HTTPException):
                with review.reviewed_request("generate", self.payload, approved["receipt"], self.actor):
                    nodes.generate_summary(state)
        self.assertEqual(1, model.invoke.call_count)

    def test_audio_withdrawal_suppresses_result_and_cleans_temporary_file(self):
        def transcribe(*args, **kwargs):
            self.allowed = False
            return Mock()
        with patch.object(audio, "current_audio_engine", return_value="clova"), \
                patch.object(audio, "persist_upload_to_temp", AsyncMock(return_value=SimpleNamespace(temp_path="synthetic-only"))), \
                patch.object(audio, "get_transcription_service", return_value=Mock(transcribe=transcribe)), \
                patch.object(audio, "cleanup_temp_file") as cleanup:
            response = TestClient(app).post("/api/audio/transcribe",
                data={"case_id": self.payload.case_id, "cloud_audio_consent": "true", "cloud_audio_provider": "clova"},
                files={"file": ("synthetic.wav", b"synthetic", "audio/wav")})
            self.assertEqual(403, response.status_code)
            cleanup.assert_called_once_with("synthetic-only")

    def test_memory_case_is_resolved_from_owned_metadata(self):
        storage = Mock()
        storage.maybe_single.return_value = {"case_id": self.payload.case_id, "user_id": str(self.actor)}
        with patch.object(supabase_storage, "_storage_for_actor", return_value=storage):
            self.assertEqual(self.payload.case_id, permission.processing_case("memory", {"note_id": "synthetic-note"}, self.actor))
            self.assertEqual("case_id,user_id", storage.maybe_single.call_args.args[1]["select"])
            storage.maybe_single.return_value["user_id"] = "synthetic-B"
            with self.assertRaises(HTTPException):
                permission.processing_case("memory", {"note_id": "synthetic-note"}, self.actor)
