"""Offline regressions for enabling confirmed prior-session retrieval."""
import copy
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from app.core.config import settings
from app.graph import nodes
from app.schemas.note import SessionInput
from app.services import retrieval
from test_security_retrieval_privacy import NOTE, SESSION, SyntheticStorage


class PriorSessionRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.multiple(settings, enable_rag=True,
                                               enable_dense_retrieval=False))
        self.client = SyntheticStorage()
        self.input = SessionInput(case_id="synthetic-case", session_number=2,
                                  counselor_memo="Synthetic current material", transcript_text="",
                                  insight_lens="none")
        self.state = {"session_input": self.input, "actor": "synthetic-owner"}
        self.state.update(nodes.sanitize_input(self.state))
        self.stack.enter_context(patch.object(nodes, "_storage_for_actor", return_value=self.client))
        self.stack.enter_context(patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")))

    def retrieve(self, number=2):
        return retrieval.retrieve_case_context(
            "synthetic-case", user_id="synthetic-owner", current_session_number=number,
            confirmed_only=True, storage_client=self.client,
        )

    def test_only_strictly_earlier_sessions_are_admitted_even_if_store_ignores_filter(self):
        self.client.tables["sessions"].extend([
            {"id": "current", "session_number": 2},
            {"id": "future", "session_number": 3},
            {"id": "unknown", "session_number": None},
        ])
        self.assertEqual([item.session_id for item in self.retrieve()], [SESSION])
        query = self.client.calls[0][1]
        self.assertEqual(query["session_number"], "lt.2")
        self.assertEqual(query["user_id"], "eq.synthetic-owner")
        self.assertEqual(query["case_id"], "eq.synthetic-case")

    def test_first_session_has_no_prior_context(self):
        self.assertEqual(self.retrieve(1), [])
        self.assertEqual([table for table, _ in self.client.calls], ["sessions"])

    def test_unconfirmed_demo_and_other_document_types_are_not_sources(self):
        original = copy.deepcopy(self.client.tables["generated_notes"][0])
        for change in ({"confirmation_status": "draft"}, {"confirmation_status": "demo_confirmed"},
                       {"note_type": "supervision_report"}, {"note_type": "termination_report"},
                       {"case_id": "foreign-case"}, {"user_id": "foreign-user"}):
            with self.subTest(change=change):
                self.client.tables["generated_notes"] = [{**original, **change}]
                self.assertEqual(self.retrieve(), [])

    def test_confirmed_record_supersedes_unreviewed_draft_and_raw_evidence(self):
        confirmed = self.client.tables["generated_notes"][0]
        self.client.tables["generated_notes"].insert(0, {
            **confirmed, "id": "newer-draft", "confirmation_status": "draft",
            "confirmed_json": {}, "draft_json": {"session_content": {"text": "REMOVED_RAW_MARKER"}},
        })
        self.client.tables["evidence_items"][0]["source_text"] = "REMOVED_RAW_MARKER"
        items = self.retrieve()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].evidence_items, [])
        self.assertNotIn("REMOVED_RAW_MARKER", items[0].model_dump_json())
        self.assertNotIn("evidence_items", [table for table, _ in self.client.calls])
        query = next(query for table, query in self.client.calls if table == "generated_notes")
        self.assertEqual(query["confirmation_status"], "eq.confirmed")
        self.assertEqual(query["note_type"], "eq.session_note")

    def test_node_uses_prior_confirmed_boundary_and_preserves_source(self):
        result = nodes.retrieve_case_memory(self.state)
        self.assertEqual(len(result["retrieved_case_context"]), 1)
        self.assertEqual(result["retrieved_case_context"][0].source_ref, f"stored_session_note:{SESSION}")
        self.assertEqual(self.client.calls[0][1]["session_number"], "lt.2")

    def test_all_confirmed_fields_are_available_to_source_validation(self):
        self.client.tables["generated_notes"][0]["confirmed_json"]["sections"]["next_plan"] = "PRIOR_PLAN_MARKER"
        items = self.retrieve()
        catalog = nodes._source_catalog(self.state["sanitized_input"], items)
        self.assertIn("PRIOR_PLAN_MARKER", catalog[f"stored_session_note:{SESSION}"])

    def test_disabled_rag_and_quick_summary_never_read_history(self):
        with patch.object(settings, "enable_rag", False):
            self.assertEqual(nodes.retrieve_case_memory(self.state)["retrieved_case_context"], [])
        self.assertEqual(nodes.retrieve_case_memory({**self.state, "allow_retrieval": False})["retrieved_case_context"], [])
        self.assertEqual(self.client.calls, [])


if __name__ == "__main__":
    unittest.main()
