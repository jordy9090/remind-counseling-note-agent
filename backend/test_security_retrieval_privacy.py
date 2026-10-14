"""Synthetic, offline checks for the case-memory reuse boundary."""
import copy
import json
import sys
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

from app.core.config import settings
from app.graph import nodes
from app.schemas.note import SessionInput, StructuredCaseData
from app.services import grounded_generation, retrieval
from app.services.deidentification import deidentify_text


EMAIL = "synthetic-contact@example.invalid"
PHONE = "010-1234-5678"
TEXT = f"Practised grounding. Contact {EMAIL}; {PHONE}."
SESSION = "11111111-1111-4111-8111-111111111111"
NOTE = "22222222-2222-4222-8222-222222222222"
REF = f"confirmed_note:{NOTE}:session_content"


class SyntheticStorage:
    retrieval_enabled = True

    def __init__(self):
        self.tables = {
            "sessions": [{"id": SESSION, "session_number": 1, "session_date": "2026-10-13"}],
            "generated_notes": [{"id": NOTE, "user_id": "synthetic-owner", "case_id": "synthetic-case",
                "session_id": SESSION, "confirmation_status": "confirmed", "confirmed_json": {
                "sections": {"session_content": TEXT},
                "nested": [{"source_ref": EMAIL, "id": PHONE, "metadata": {EMAIL: TEXT}}],
                "score": 0.75, "visible": True, "empty": None,
            }}],
            "evidence_items": [{"id": NOTE, "session_id": SESSION,
                "source_text": TEXT, "source_type": EMAIL, "linked_field": PHONE}],
        }
        self.rows = []
        self.calls = []

    def select(self, table, query):
        self.calls.append((table, query))
        return self.tables.get(table, [])

    def rpc(self, name, params):
        self.calls.append((name, params))
        return self.rows

    def insert(self, *args, **kwargs):
        return []


class ReachedSummary(Exception):
    pass


class RetrievalPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target in ("socket.create_connection", "socket.socket.connect"):
            self.stack.enter_context(patch(target, side_effect=AssertionError("Network forbidden")))
        self.stack.enter_context(patch.multiple(settings, enable_rag=True,
            enable_dense_retrieval=True, enable_raw_region_grounding=False,
            use_stub=False, openai_api_key="synthetic-offline"))
        self.client = SyntheticStorage()
        self.input = SessionInput(case_id="synthetic-case", session_number=2,
            session_date="2026-10-13", counselor_memo="Practised grounding.", transcript_text="", insight_lens="none")
        self.state = {"session_input": self.input, "actor": "synthetic-owner"}
        self.state.update(nodes.sanitize_input(self.state))
        self.state.update(nodes.formulate_retrieval_query(self.state))
        self.stack.enter_context(patch.object(nodes, "_storage_for_actor", return_value=self.client))
        self.stack.enter_context(patch.object(retrieval, "embed_query", return_value=[0.0, 1.0]))

    def assertMasked(self, value):
        text = json.dumps(value, ensure_ascii=False, default=str)
        self.assertNotIn(EMAIL, text)
        self.assertNotIn(PHONE, text)

    def context(self):
        return retrieval.retrieve_case_context("synthetic-case", user_id="synthetic-owner", storage_client=self.client)

    def test_recency_masks_all_content_and_preserves_storage_and_citations(self):
        original = copy.deepcopy(self.client.tables)
        item = self.context()[0]
        self.assertMasked(item.model_dump())
        self.assertIn("Practised grounding.", item.summary)
        self.assertEqual(item.source_ref, f"stored_session_note:{SESSION}")
        self.assertEqual(item.session_id, SESSION)
        self.assertEqual(item.session_number, 1)
        self.assertEqual(item.session_date, "2026-10-13")
        self.assertEqual(item.evidence_items[0].id, NOTE)
        self.assertEqual(item.evidence_items[0].source_ref, f"stored_evidence:{NOTE}")
        self.assertEqual(item.confirmed_note["score"], 0.75)
        self.assertIs(item.confirmed_note["visible"], True)
        self.assertIsNone(item.confirmed_note["empty"])
        self.assertEqual(self.client.tables, original)

    def test_draft_summary_fallback_is_masked(self):
        self.client.tables["generated_notes"][0] = {"session_id": SESSION,
            "user_id": "synthetic-owner", "case_id": "synthetic-case",
            "confirmed_json": {}, "draft_json": {"session_content": {"text": TEXT}}}
        item = self.context()[0]
        self.assertMasked(item.summary)
        self.assertIn("Practised grounding.", item.summary)

    def test_masked_keys_do_not_drop_values_on_collision(self):
        content = {EMAIL: "first clinical detail", "another@example.invalid": "second clinical detail"}
        self.client.tables["generated_notes"][0]["confirmed_json"] = content
        result = self.context()[0].confirmed_note
        self.assertMasked(result)
        self.assertEqual(sorted(result.values()), sorted(content.values()))

    def test_many_colliding_keys_have_bounded_work_and_preserve_values(self):
        count = 512
        content = {f"synthetic-{index}@example.invalid": index for index in range(count)}
        # Count work instead of timing the machine: a generous per-entry budget
        # tolerates refactoring but rejects repeated scans of all earlier keys.
        steps = 0
        def bound_work(frame, event, arg):
            nonlocal steps
            if event == "line" and frame.f_code is retrieval._mask_content.__code__:
                steps += 1
                if steps > count * 100:
                    raise AssertionError("Masking exceeded a linear work budget")
            return bound_work
        previous_trace = sys.gettrace()
        try:
            sys.settrace(bound_work)
            masked = retrieval._mask_content(content)
        finally:
            sys.settrace(previous_trace)
        self.assertEqual(sorted(masked.values()), list(range(count)))
        self.assertNotIn("@example.invalid", json.dumps(masked))

    def test_literal_suffix_keys_and_nested_collisions_preserve_all_values(self):
        token = deidentify_text(EMAIL)[0]
        content = {token: "literal", f"{token} [2]": "reserved suffix",
            EMAIL: "first clinical detail", "another@example.invalid": "second clinical detail",
            "nested": {EMAIL: "nested first", "another@example.invalid": "nested second"}}
        masked = retrieval._mask_content(content)
        self.assertEqual(len(masked), len(content))
        self.assertEqual(masked[token], "literal")
        self.assertEqual(masked[f"{token} [2]"], "reserved suffix")
        self.assertEqual(masked[f"{token} [3]"], "first clinical detail")
        self.assertEqual(masked[f"{token} [4]"], "second clinical detail")
        self.assertEqual(list(masked["nested"].values()), ["nested first", "nested second"])
        self.assertEqual(retrieval._mask_content(masked), masked)

    def test_recency_and_empty_dense_fallback_mask_both_model_invocations(self):
        for dense in (False, True):
            with self.subTest(dense=dense), patch.object(settings, "enable_dense_retrieval", dense):
                state = dict(self.state)
                state.update(nodes.retrieve_case_memory(state))
                self.assertEqual(len(state["retrieved_case_context"]), 1)
                captured = []
                def factory(schema):
                    def invoke(prompt):
                        captured.append((schema.__name__, prompt))
                        if schema is StructuredCaseData:
                            return nodes._mock_structured_case(state["sanitized_input"], [])
                        raise ReachedSummary()
                    return Mock(invoke=Mock(side_effect=invoke))
                with patch.object(nodes, "get_structured_llm", side_effect=factory):
                    state.update(nodes.structure_session(state))
                    state.update(nodes.map_evidence(state))
                    with self.assertRaises(ReachedSummary):
                        nodes.generate_summary(state)
                self.assertEqual([name for name, _ in captured], ["StructuredCaseData", "SessionSummaryDraft"])
                for _, prompt in captured:
                    self.assertMasked(prompt)
                    self.assertIn("Practised grounding.", prompt)

    def test_legacy_dense_content_and_grounded_prompt_are_masked(self):
        self.client.rows = [{"chunk_id": NOTE, "session_id": SESSION, "source_note_id": NOTE,
            "source_ref": REF, "chunk_text": TEXT, "field_type": "session_content",
            "session_number": 1, "session_date": "2026-10-13", "similarity_score": 0.75,
            "metadata": {"nested": [{"source_refs": [EMAIL], PHONE: TEXT}], "count": 2}}]
        original = copy.deepcopy(self.client.rows)
        chunks = retrieval.retrieve_case_memory_chunks(query_text="grounding", counselor_id="synthetic-owner",
            case_id="synthetic-case", storage_client=self.client)
        self.assertMasked(vars(chunks[0]))
        self.assertEqual(chunks[0].source_ref, REF)
        self.assertEqual(chunks[0].source_note_id, NOTE)
        self.assertEqual(chunks[0].similarity_score, 0.75)
        self.assertEqual(chunks[0].metadata["count"], 2)
        self.assertEqual(self.client.rows, original)
        self.assertMasked([item.model_dump() for item in retrieval.chunks_to_case_context(chunks)])
        context = grounded_generation.assemble_grounding_context(needs=[], raw_regions_by_need={}, counselor_memory_chunks=chunks)
        model = Mock()
        with patch.object(grounded_generation, "get_structured_llm", return_value=model):
            grounded_generation.generate_grounded_claims(self.state["sanitized_input"], context)
        prompt = model.invoke.call_args.args[0]
        self.assertMasked(prompt)
        self.assertIn("Practised grounding.", prompt)

    def test_direct_dense_projection_is_safe_and_does_not_mutate(self):
        chunk = retrieval.RetrievalChunk(chunk_id=NOTE, session_id=SESSION,
            chunk_text=TEXT, source_ref=REF, field_type=EMAIL, retrieval_method="case_memory_dense")
        original = copy.deepcopy(chunk)
        self.assertMasked([item.model_dump() for item in retrieval.chunks_to_case_context([chunk])])
        self.assertEqual(chunk, original)

    def test_existing_masked_text_is_stable_and_rag_disabled_does_no_work(self):
        masked = deidentify_text(TEXT)[0]
        self.client.tables["generated_notes"][0]["confirmed_json"] = {"sections": {"session_content": masked}}
        self.assertEqual(self.context()[0].summary, masked)
        self.client.calls.clear()
        with patch.object(settings, "enable_rag", False):
            self.assertEqual(self.context(), [])
            self.assertEqual(nodes.retrieve_case_memory(self.state)["retrieved_case_context"], [])
        self.assertEqual(self.client.calls, [])


if __name__ == "__main__":
    unittest.main()
