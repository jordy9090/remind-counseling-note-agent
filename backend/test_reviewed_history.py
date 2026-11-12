"""Synthetic checks for prior-session retrieval through the existing review gate."""
import copy
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from fastapi import HTTPException

from app.api.security import AuthenticatedActor
from app.core.config import settings
from app.graph import nodes
from app.schemas.note import SessionInput
from app.services import deid_review as review
from app.services.qwen_deidentification import Entities, PendingDetection
from test_security_retrieval_privacy import SyntheticStorage, SESSION


class ReviewedHistoryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.multiple(settings, enable_rag=True, require_deid_review=True,
            enable_dense_retrieval=False, deid_review_signing_key="synthetic-review-key-" * 3))
        self.stack.enter_context(patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")))
        self.client = SyntheticStorage()
        self.client.tables["generated_notes"][0]["confirmed_json"] = {"sections": {
            "session_content": "HISTORICAL_NAME discussed a previous plan.", "next_plan": "PRIOR_PLAN"}}
        self.storage = self.stack.enter_context(patch("app.services.supabase_storage._storage_for_actor", return_value=self.client))
        self.detect = self.stack.enter_context(patch.object(review, "detect_entities", return_value=Entities(entities=[])))
        self.actor = AuthenticatedActor("synthetic-owner", "synthetic-user-jwt")
        self.payload = SessionInput(case_id="synthetic-case", session_number=2,
            counselor_memo="Current material", transcript_text="", insight_lens="none").model_dump()

    def start(self, purpose="generate", payload=None, **kwargs):
        return review.start_review(review.ReviewStart(purpose=purpose, payload=payload or self.payload, **kwargs), self.actor)

    def confirm(self, found, edits=None, purpose="generate"):
        return review.confirm_review(review.ReviewConfirm(purpose=purpose, payload=found["payload"],
            detection_token=found["detection_token"], edits=edits or []), self.actor)

    def test_history_is_detected_reviewed_and_uses_authenticated_storage(self):
        found = self.start()
        self.assertIs(self.storage.call_args.args[0], self.actor)
        self.assertEqual(1, len(found["payload"]["prior_session_context"]))
        material = " ".join(self.detect.call_args.args[0])
        self.assertIn("PRIOR_PLAN", material)
        self.assertNotIn(SESSION, material)
        self.assertTrue(any(source["key"].startswith("/prior_session_context/") for source in found["sources"]))

    def test_only_reviewed_edits_enter_graph_context_and_context_is_reset(self):
        found = self.start()
        edits = [review.SpanEdit(path=source["key"], start=source["text"].index("HISTORICAL_NAME"),
            end=source["text"].index("HISTORICAL_NAME") + len("HISTORICAL_NAME"),
            original="HISTORICAL_NAME", replacement="[인물 1]")
            for source in found["sources"] if "HISTORICAL_NAME" in source["text"]]
        approved = self.confirm(found, edits)
        payload = SessionInput(**approved["payload"])
        with review.reviewed_request("generate", payload, approved["receipt"], self.actor):
            context = review.reviewed_prior_sessions()
            state = {"session_input": payload, "actor": self.actor, "allow_retrieval": False,
                     "reviewed_case_context": context}
            state.update(nodes.sanitize_input(state))
            result = nodes.retrieve_case_memory(state)
            self.assertNotIn("HISTORICAL_NAME", result["retrieved_case_context"][0].model_dump_json())
            self.assertEqual(f"stored_session_note:{SESSION}", context[0].source_ref)
        self.assertIsNone(review.reviewed_prior_sessions())

    def test_changed_or_deleted_source_invalidates_receipt(self):
        approved = self.confirm(self.start())
        for notes in ([], [{**self.client.tables["generated_notes"][0], "confirmed_json": {"sections": {"next_plan": "CHANGED"}}}]):
            with self.subTest(deleted=not notes):
                self.client.tables["generated_notes"] = notes
                with self.assertRaises(HTTPException) as caught:
                    with review.reviewed_request("generate", SessionInput(**approved["payload"]), approved["receipt"], self.actor):
                        self.fail("Stale history was admitted")
                self.assertEqual(409, caught.exception.status_code)

    def test_tampered_history_is_rejected_and_off_clears_submitted_context(self):
        found = self.start()
        tampered = copy.deepcopy(found["payload"])
        tampered["prior_session_context"][0]["summary"] = "FORGED"
        with self.assertRaises(HTTPException):
            review.confirm_review(review.ReviewConfirm(purpose="generate", payload=tampered,
                detection_token=found["detection_token"]), self.actor)
        with patch.object(settings, "enable_rag", False):
            off = self.start(payload=tampered)
        self.assertEqual([], off["payload"]["prior_session_context"])

    def test_guest_never_reads_history_and_first_session_has_empty_snapshot(self):
        with patch.object(review, "_history_snapshot", wraps=review._history_snapshot):
            guest = review.start_review(review.ReviewStart(purpose="generate", payload=self.payload), "guest:synthetic")
        self.assertEqual([], guest["payload"]["prior_session_context"])
        self.assertEqual([], self.client.calls)
        first = self.start(payload={**self.payload, "session_number": 1})
        self.assertEqual([], first["payload"]["prior_session_context"])

    def test_pending_poll_binds_same_history_and_rejects_changed_history(self):
        self.detect.return_value = PendingDetection(job_id="synthetic-job")
        pending = self.start()
        self.detect.return_value = Entities(entities=[])
        completed = self.start(job_token=pending["job_token"])
        self.assertEqual(1, len(completed["payload"]["prior_session_context"]))
        self.client.tables["generated_notes"] = []
        with self.assertRaises(HTTPException):
            self.start(job_token=pending["job_token"])

    def test_recomposition_reviews_history_and_quick_summary_does_not(self):
        found = self.start("recompose", {"session_input": self.payload})
        self.assertEqual(1, len(found["payload"]["session_input"]["prior_session_context"]))
        approved = self.confirm(found, purpose="recompose")
        with review.reviewed_request("recompose", review.RecomposeNoteRequest(**approved["payload"]), approved["receipt"], self.actor):
            self.assertEqual(1, len(review.reviewed_prior_sessions()))
        self.client.calls.clear()
        self.start("quick", {"text": "Current material only"})
        self.assertEqual([], self.client.calls)


if __name__ == "__main__":
    unittest.main()
