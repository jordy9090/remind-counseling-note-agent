"""Offline contracts for the authenticated two-stage PoC AI approval boundary."""
import copy
import os
import unittest
from contextlib import ExitStack
from unittest.mock import patch

if os.environ.get("REMIND_POC_OFFLINE") != "1":
    raise unittest.SkipTest("Use backend/tests/run_poc_review.py")

from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.api.security import AuthenticatedActor, require_preview_access
from app.core.config import settings
from app.schemas.note import SessionInput, RecomposeNoteRequest
from app.services import deid_review as review
from app.services.qwen_deidentification import Entities, PendingDetection
from api.notes.generate import app
from api.notes.recompose import app as recompose_app

RAW = "SYNTHETIC-UNREVIEWED-POC-INPUT"


class PoCApprovalTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(settings.__dict__, {
            "poc_mode": True, "require_deid_review": False, "enable_rag": False,
            "deid_review_signing_key": "synthetic-review-secret-" * 3,
        }))
        self.actor = AuthenticatedActor("synthetic-owner-A", "synthetic-jwt-A")
        self.detect = self.stack.enter_context(patch.object(review, "detect_entities", return_value=Entities(entities=[])))
        self.payload = SessionInput(case_id="synthetic-case", session_number=2,
                                    counselor_memo=RAW, transcript_text="").model_dump(mode="json")
        app.dependency_overrides[require_preview_access] = lambda: self.actor
        recompose_app.dependency_overrides[require_preview_access] = lambda: self.actor
        self.addCleanup(app.dependency_overrides.clear)
        self.addCleanup(recompose_app.dependency_overrides.clear)

    def prepare(self, purpose="generate", payload=None):
        # An explicit assertion gives a useful red result before this endpoint exists.
        self.assertTrue(hasattr(review, "prepare_review"), "Local-only preparation stage is missing")
        return review.prepare_review(review.ReviewStart(purpose=purpose, payload=payload or self.payload), self.actor)

    def approve(self, purpose="generate", payload=None):
        prepared = self.prepare(purpose, payload)
        found = review.start_review(review.ReviewStart(purpose=purpose, payload=prepared["payload"],
            preparation_token=prepared["preparation_token"]), self.actor)
        return review.confirm_review(review.ReviewConfirm(purpose=purpose, payload=found["payload"],
            detection_token=found["detection_token"]), self.actor)

    def test_missing_pre_detection_approval_never_calls_ai(self):
        with self.assertRaises(HTTPException) as caught:
            review.start_review(review.ReviewStart(purpose="generate", payload=self.payload), self.actor)
        self.assertEqual(409, caught.exception.status_code)
        self.detect.assert_not_called()

    def test_disabled_legacy_flag_cannot_open_direct_generation_or_recompose(self):
        for application, path, payload, target in (
            (app, "/api/notes/generate", self.payload, "_generate_reviewed"),
            (recompose_app, "/api/notes/recompose", {"session_input": self.payload}, "recompose_note_with_cache"),
        ):
            with self.subTest(path=path), patch("app.api.routes.notes." + target) as model:
                response = TestClient(application, raise_server_exceptions=False).post(path, json=payload)
                self.assertEqual(409, response.status_code)
                model.assert_not_called()
        with self.assertRaises(HTTPException):
            review.require_reviewed_egress()
        self.assertFalse(review.embedding_is_reviewed(RAW))

    def test_guest_cannot_obtain_or_reuse_ai_approval(self):
        with self.assertRaises(HTTPException) as caught:
            review.start_review(review.ReviewStart(purpose="quick", payload={"text": RAW}), "guest:shared-ip")
        self.assertEqual(401, caught.exception.status_code)
        self.detect.assert_not_called()
        response = TestClient(app).post("/api/notes/quick-summary", json={"text": RAW})
        self.assertEqual(401, response.status_code)

    def test_prepare_is_local_and_actor_case_session_and_input_are_bound(self):
        prepared = self.prepare()
        self.detect.assert_not_called()
        self.assertIn(RAW, [item["text"] for item in prepared["sources"]])
        for changes, actor in (({"case_id": "other-case"}, self.actor), ({"session_number": 3}, self.actor),
                ({"counselor_memo": RAW + " edited"}, self.actor), ({}, AuthenticatedActor("other-owner", "other-jwt"))):
            with self.subTest(changes=tuple(changes), actor=str(actor)), self.assertRaises(HTTPException):
                review.start_review(review.ReviewStart(purpose="generate", payload={**prepared["payload"], **changes},
                    preparation_token=prepared["preparation_token"]), actor)
        self.detect.assert_not_called()

    def test_approved_request_retry_and_context_reset(self):
        approved = self.approve()
        payload = SessionInput(**approved["payload"])
        for _ in range(2):
            with review.reviewed_request("generate", payload, approved["receipt"], self.actor):
                review.require_reviewed_egress()
                self.assertTrue(review.embedding_is_reviewed(RAW))
            self.assertIsNone(review._approved.get())
        with self.assertRaises(RuntimeError):
            with review.reviewed_request("generate", payload, approved["receipt"], self.actor):
                raise RuntimeError("Synthetic cancellation or provider failure")
        self.assertIsNone(review._approved.get())
        for changed in ({"case_id": "other-case"}, {"session_number": 3}, {"transcript_text": "edited"}):
            with self.assertRaises(HTTPException):
                with review.reviewed_request("generate", payload.model_copy(update=changed), approved["receipt"], self.actor):
                    self.fail("Changed version was accepted")
        with self.assertRaises(HTTPException):
            with review.reviewed_request("recompose", RecomposeNoteRequest(session_input=payload), approved["receipt"], self.actor):
                self.fail("Wrong purpose accepted")

    def test_prior_history_change_blocks_detection_and_generation(self):
        with patch.object(settings, "enable_rag", True), patch.object(review, "_history_snapshot", return_value=[]) as history:
            prepared = self.prepare()
            history.return_value = [{"summary": "NEW-SYNTHETIC-HISTORY"}]
            with self.assertRaises(HTTPException):
                review.start_review(review.ReviewStart(purpose="generate", payload=prepared["payload"],
                    preparation_token=prepared["preparation_token"]), self.actor)
            self.detect.assert_not_called()
            history.return_value = []
            approved = self.approve()
            history.return_value = [{"summary": "NEW-SYNTHETIC-HISTORY"}]
            with self.assertRaises(HTTPException):
                with review.reviewed_request("generate", SessionInput(**approved["payload"]), approved["receipt"], self.actor):
                    self.fail("Stale history accepted")

    def test_pending_detection_poll_preserves_exact_approval(self):
        prepared = self.prepare()
        self.detect.return_value = PendingDetection(job_id="synthetic-job")
        pending = review.start_review(review.ReviewStart(purpose="generate", payload=prepared["payload"],
            preparation_token=prepared["preparation_token"]), self.actor)
        self.detect.return_value = Entities(entities=[])
        found = review.start_review(review.ReviewStart(purpose="generate", payload=prepared["payload"],
            preparation_token=prepared["preparation_token"], job_token=pending["job_token"]), self.actor)
        self.assertIn("detection_token", found)
        self.assertEqual("synthetic-job", self.detect.call_args.kwargs["job_id"])

    def test_local_prepare_api_is_registered_without_ai_call(self):
        with patch("app.api.routes.notes._require_supabase_user", return_value=self.actor):
            response = TestClient(app).post("/api/notes/deidentification-prepare", json={"purpose": "generate", "payload": self.payload},
                headers={"Authorization": "Bearer synthetic-jwt-A"})
        self.assertEqual(200, response.status_code)
        self.assertIn("preparation_token", response.json())
        self.detect.assert_not_called()

    def test_recompose_prompt_options_are_visible_before_approval(self):
        prepared = self.prepare("recompose", {"session_input": self.payload,
            "visible_section_ids": ["SYNTHETIC-API-CONTROLLED-TEXT"]})
        self.assertIn("SYNTHETIC-API-CONTROLLED-TEXT", [item["text"] for item in prepared["sources"]])

    def test_approved_direct_generation_and_recomposition_still_work(self):
        from test_poc_storage import synthetic_result
        from app.schemas.note import RecomposeNoteResponse
        for purpose, application, target in (("generate", app, "_generate_reviewed"),
                ("recompose", recompose_app, "recompose_note_with_cache")):
            approved = self.approve(purpose, self.payload if purpose == "generate" else {"session_input": self.payload})
            result = synthetic_result()
            if purpose == "recompose":
                result = RecomposeNoteResponse(result=result, visible_section_ids=[], cache_key="synthetic", cache_hit=False)
            with self.subTest(purpose=purpose), patch("app.api.routes.notes." + target, return_value=result) as model:
                response = TestClient(application).post("/api/notes/" + purpose, json=approved["payload"],
                    headers={"X-Review-Receipt": approved["receipt"]})
                self.assertEqual(200, response.status_code)
                model.assert_called_once()
                self.assertEqual(RAW, (model.call_args.args[0] if purpose == "generate" else model.call_args.args[0].session_input).counselor_memo)
