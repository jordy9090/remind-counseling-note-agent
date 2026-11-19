"""Offline regression for reviewed history reaching the actual graph prompt path."""
import os
import unittest
from contextlib import ExitStack, nullcontext
from unittest.mock import Mock, patch

if os.environ.get("REMIND_POC_OFFLINE") != "1":
    raise unittest.SkipTest("Use backend/tests/run_poc_review.py")

from app.api.security import AuthenticatedActor
from app.core.config import settings
from app.graph import graph, nodes
from app.schemas.note import SessionInput
from app.services import deid_review as review
from app.services.qwen_deidentification import Entities
from test_security_retrieval_privacy import SyntheticStorage


PRIVATE = "SYNTHETIC_HISTORICAL_NAME"
REPLACEMENT = "[reviewed person]"


class ReachedPrompt(Exception):
    """Stop at the mocked external sink without completing or storing a note."""


class PoCReviewedHistoryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.multiple(settings, poc_mode=True,
            require_deid_review=False, enable_rag=True, enable_dense_retrieval=False,
            enable_raw_region_grounding=False, use_stub=False,
            openai_api_key="synthetic-offline-key",
            deid_review_signing_key="synthetic-history-review-key-" * 3))
        self.storage = SyntheticStorage()
        self.storage.tables["generated_notes"][0]["confirmed_json"] = {
            "sections": {"session_content": PRIVATE + " discussed an earlier plan."}}
        self.stack.enter_context(patch("app.services.supabase_storage._storage_for_actor",
            return_value=self.storage))
        self.stack.enter_context(patch.object(nodes, "_storage_for_actor", return_value=self.storage))
        self.stack.enter_context(patch.object(review, "detect_entities", return_value=Entities(entities=[])))
        self.actor = AuthenticatedActor("synthetic-owner", "synthetic-jwt")
        self.payload = SessionInput(case_id="synthetic-case", session_number=2,
            counselor_memo="Synthetic current session material.", transcript_text="",
            insight_lens="none").model_dump(mode="json")
        self.initial_state = None
        self.prompt = ""

    def approve(self):
        prepared = review.prepare_review(review.ReviewStart(purpose="generate", payload=self.payload), self.actor)
        found = review.start_review(review.ReviewStart(purpose="generate", payload=prepared["payload"],
            preparation_token=prepared["preparation_token"]), self.actor)
        edits = [review.SpanEdit(path=source["key"], start=source["text"].index(PRIVATE),
            end=source["text"].index(PRIVATE) + len(PRIVATE), original=PRIVATE, replacement=REPLACEMENT)
            for source in found["sources"] if PRIVATE in source["text"]]
        return review.confirm_review(review.ReviewConfirm(purpose="generate", payload=found["payload"],
            detection_token=found["detection_token"], edits=edits), self.actor)

    def reach_prompt(self, payload, receipt=None, *, allow_retrieval=True):
        def invoke_selected_nodes(initial):
            self.initial_state = initial.copy()
            state = initial.copy()
            state.update(nodes.sanitize_input(state))
            state.update(nodes.retrieve_case_memory(state))
            return nodes.structure_session(state)

        def external_sink(prompt):
            review.require_reviewed_egress()
            self.prompt = prompt
            raise ReachedPrompt()

        context = review.reviewed_request("generate", payload, receipt, self.actor) if receipt else nullcontext()
        with patch.object(graph.note_graph, "invoke", side_effect=invoke_selected_nodes), \
                patch.object(nodes, "get_structured_llm", return_value=Mock(invoke=external_sink)), \
                self.assertRaises(ReachedPrompt):
            with context:
                # Ignore approval/revision reads; only graph-time storage reads matter here.
                self.storage.calls.clear()
                graph.run_note_pipeline(payload, actor=self.actor, allow_retrieval=allow_retrieval)
        self.assertIsNone(review.reviewed_prior_sessions())
        self.assertIsNone(review._approved.get())

    def assert_reviewed_history_only(self):
        approved = self.approve()
        self.assertNotIn(PRIVATE, str(approved["payload"]["prior_session_context"]))
        self.assertIn(REPLACEMENT, str(approved["payload"]["prior_session_context"]))
        self.reach_prompt(SessionInput(**approved["payload"]), approved["receipt"])
        self.assertTrue(PRIVATE not in self.prompt, "The graph restored text removed during human review")
        self.assertTrue(REPLACEMENT in self.prompt, "The graph dropped the counselor-reviewed replacement")
        self.assertFalse(self.initial_state["allow_retrieval"])
        self.assertEqual([], self.storage.calls, "Approved history was replaced with a fresh storage lookup")

    def test_poc_overrides_disabled_legacy_flag_at_history_prompt_boundary(self):
        self.assert_reviewed_history_only()

    def test_legacy_review_mode_preserves_the_same_approved_snapshot(self):
        with patch.multiple(settings, poc_mode=False, require_deid_review=True):
            self.assert_reviewed_history_only()

    def test_non_poc_unreviewed_mode_preserves_explicit_retrieval(self):
        with patch.multiple(settings, poc_mode=False, require_deid_review=False):
            self.reach_prompt(SessionInput(**self.payload))
        self.assertTrue(self.initial_state["allow_retrieval"])
        self.assertTrue(PRIVATE in self.prompt, "Explicit unreviewed retrieval lost its synthetic source")
        self.assertTrue(self.storage.calls)

    def test_disabled_rag_never_restores_history(self):
        with patch.object(settings, "enable_rag", False):
            approved = self.approve()
            self.assertEqual([], approved["payload"]["prior_session_context"])
            self.reach_prompt(SessionInput(**approved["payload"]), approved["receipt"])
        self.assertNotIn(PRIVATE, self.prompt)
        self.assertEqual([], self.storage.calls)

    def test_explicit_no_retrieval_does_not_add_reviewed_history(self):
        approved = self.approve()
        self.reach_prompt(SessionInput(**approved["payload"]), approved["receipt"], allow_retrieval=False)
        self.assertIsNone(self.initial_state["reviewed_case_context"])
        self.assertNotIn(PRIVATE, self.prompt)
        self.assertNotIn(REPLACEMENT, self.prompt)
        self.assertEqual([], self.storage.calls)
