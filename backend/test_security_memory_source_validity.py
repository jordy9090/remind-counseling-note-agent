"""Synthetic source-admission checks; no provider or database network is used."""
from __future__ import annotations

import copy
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.api.security import AuthenticatedActor
from app.core.config import settings
from app.main import app
from app.schemas.note import RecomposeNoteRequest, RetrievedCaseContextItem
from app.services import recompose_cache, retrieval
from app.services.supabase_storage import SupabaseStorage, SupabaseStorageError
from test_persistence_workflow import TOKEN, offline_environment


OWNER, CASE, SESSION, NOTE = "synthetic-user-a", "synthetic-case", "synthetic-session", "synthetic-note"
OLD, NEW = "SYNTHETIC SUPERSEDED CONTENT", "SYNTHETIC CURRENT CONTENT"


class MemorySourceTestBase(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.store = self.stack.enter_context(offline_environment())
        request = self.store.request
        def ordered_request(method, table, **kwargs):
            query = dict(kwargs.get("query") or {})
            if method != "GET":
                return request(method, table, **kwargs)
            order, limit, offset = query.pop("order", ""), query.pop("limit", None), int(query.pop("offset", 0))
            rows = request(method, table, **{**kwargs, "query": query})
            for clause in reversed(order.split(",") if order else []):
                field, direction = clause.split(".")
                rows.sort(key=lambda row: str(row.get(field) or ""), reverse=direction == "desc")
            return rows[offset:offset + int(limit)] if limit is not None else rows[offset:]
        self.stack.enter_context(patch.object(self.store, "request", side_effect=ordered_request))
        self.stack.enter_context(patch.multiple(settings, enable_rag=True, enable_dense_retrieval=True))
        self.stack.enter_context(patch.object(retrieval, "embed_query", return_value=[0.0, 1.0]))
        self.actor = AuthenticatedActor(OWNER, TOKEN)
        self.storage = SupabaseStorage(access_token=TOKEN)
        self.client = TestClient(app, raise_server_exceptions=False)
        self.note = {"id": NOTE, "user_id": OWNER, "case_id": CASE, "session_id": SESSION,
                     "confirmation_status": "confirmed", "confirmed_at": "2026-10-14T00:00:00Z",
                     "confirmed_json": {"sections": {"session_content": OLD}},
                     "draft_json": {"session_content": {"text": OLD}}}
        self.row = {"chunk_id": "synthetic-chunk", "user_id": OWNER, "counselor_id": OWNER,
                    "case_id": CASE, "session_id": SESSION, "source_note_id": NOTE,
                    "field_type": "session_content", "chunk_text": OLD,
                    "source_ref": f"confirmed_note:{NOTE}:session_content", "similarity_score": 0.9}
        self.store.tables.update({
            "cases": [{"id": CASE, "user_id": OWNER, "counselor_id": OWNER}],
            "sessions": [{"id": SESSION, "case_id": CASE, "user_id": OWNER, "session_number": 1}],
            "generated_notes": [self.note], "case_memory_chunks": [self.row],
        })
        self.stack.enter_context(patch.object(self.storage, "rpc", side_effect=lambda *_: copy.deepcopy(self.store.tables["case_memory_chunks"])))

    def retrieve(self):
        return retrieval.retrieve_case_memory_chunks(query_text="synthetic query", counselor_id=OWNER,
                                                      case_id=CASE, storage_client=self.storage)

    def confirm(self, sections, *, create_memory=False):
        return self.client.post("/api/notes/confirm", headers={"Authorization": f"Bearer {TOKEN}"}, json={
            "note_id": NOTE, "confirmed_note": {"sections": sections}, "counselor_edited": True,
            "create_case_memory": create_memory,
        })


class MemorySourceValidityTests(MemorySourceTestBase):
    def test_normal_optout_reconfirmation_excludes_surviving_obsolete_rows(self):
        self.assertEqual(self.confirm({}).status_code, 200)
        self.assertEqual(len(self.store.tables["case_memory_chunks"]), 1, "This fix must not silently purge stored data")
        self.assertEqual(self.retrieve(), [])

    def test_creation_disabled_and_failed_replacement_never_admit_old_text(self):
        self.assertEqual(self.confirm({"session_content": NEW}, create_memory=True).status_code, 200)
        self.assertEqual(self.retrieve(), [])
        self.note["confirmed_json"] = {"sections": {"session_content": OLD}}
        request = self.store.request
        def fail_write(method, table, **kwargs):
            if method == "POST" and table == "case_memory_chunks":
                raise SupabaseStorageError("Synthetic write failure")
            return request(method, table, **kwargs)
        with patch.object(settings, "enable_case_memory", True), patch.object(settings, "enable_dense_retrieval", False), \
                patch.object(self.store, "request", side_effect=fail_write):
            self.assertEqual(self.confirm({"session_content": NEW}, create_memory=True).status_code, 500)
        self.assertEqual(self.retrieve(), [])

    def test_incomplete_embedding_response_does_not_make_old_source_retrievable(self):
        provider = Mock()
        provider.embed.return_value = []
        with patch.object(settings, "enable_case_memory", True), patch(
            "app.services.supabase_storage.get_embedding_provider", return_value=provider
        ):
            self.assertEqual(self.confirm({"session_content": NEW}, create_memory=True).status_code, 500)
        self.assertEqual(self.retrieve(), [])

    def test_same_text_reintroduced_by_newer_confirmation_is_valid(self):
        self.assertEqual(self.confirm({}).status_code, 200)
        self.assertEqual(self.confirm({"session_content": OLD}).status_code, 200)
        chunks = self.retrieve()
        self.assertEqual([chunk.chunk_text for chunk in chunks], [OLD])

    def test_source_changed_after_rpc_is_rejected_before_projection(self):
        def source_changes(*_):
            rows = copy.deepcopy(self.store.tables["case_memory_chunks"])
            self.note["confirmed_json"] = {"sections": {"session_content": NEW}}
            return rows
        with patch.object(self.storage, "rpc", side_effect=source_changes):
            self.assertEqual(self.retrieve(), [])

    def test_current_confirmed_source_supports_legacy_shapes_and_existing_masking(self):
        for content in ({"sections": {"session_content": OLD}}, {"session_content": OLD},
                        {"session_content": {"text": OLD}}):
            with self.subTest(shape=list(content)):
                self.note["confirmed_json"] = content
                self.assertEqual(self.retrieve()[0].chunk_text, OLD)
        self.note["confirmed_json"] = {"sections": {"session_content": "Contact synthetic@example.invalid"}}
        self.row["chunk_text"] = "Contact synthetic@example.invalid"
        self.assertNotIn("synthetic@example.invalid", self.retrieve()[0].chunk_text)

    def test_missing_unconfirmed_foreign_and_mismatched_sources_are_rejected(self):
        original = copy.deepcopy(self.note)
        for change in ({"user_id": "other-owner"}, {"case_id": "other-case"}, {"session_id": "other-session"},
                       {"confirmation_status": "draft"}, {"confirmed_json": {}}, {"id": "other-note"}):
            with self.subTest(change=list(change)):
                self.note.clear(); self.note.update(original); self.note.update(change)
                self.assertEqual(self.retrieve(), [])
        self.note.clear(); self.note.update(original)
        self.row["field_type"] = "unrecognized_field"
        self.assertEqual(self.retrieve(), [])
        self.row["field_type"] = "session_content"
        self.row["session_id"] = self.note["session_id"] = ""
        self.assertEqual(self.retrieve(), [])

    def test_source_read_failure_does_not_return_any_candidate_text(self):
        with patch.object(self.storage, "select", side_effect=SupabaseStorageError("SYNTHETIC PRIVATE FAILURE")):
            with self.assertRaisesRegex(RuntimeError, "source") as failure:
                self.retrieve()
        self.assertNotIn("SYNTHETIC PRIVATE FAILURE", str(failure.exception))

    def test_cleared_confirmed_summary_never_falls_back_to_old_draft(self):
        for content in ({"sections": {}}, {"sections": {"session_content": ""}}, {}, {"next_plan": NEW}):
            with self.subTest(content=content):
                self.note["confirmed_json"] = content
                result = retrieval.retrieve_case_context(CASE, user_id=OWNER, storage_client=self.storage)
                self.assertEqual(result[0].summary, "")
        self.note["confirmation_status"] = "draft"
        self.note["confirmed_json"] = {}
        self.assertEqual(retrieval.retrieve_case_context(CASE, user_id=OWNER, storage_client=self.storage)[0].summary, OLD)

    def test_recency_defensively_rejects_notes_outside_requested_scope(self):
        select = self.storage.select
        def return_unfiltered_notes(table, query):
            if table == "generated_notes":
                self.assertEqual(query.get("case_id"), f"eq.{CASE}")
                return [copy.deepcopy(self.note)]
            return select(table, query)
        original = copy.deepcopy(self.note)
        with patch.object(self.storage, "select", side_effect=return_unfiltered_notes):
            for change in ({"case_id": "other-case"}, {"user_id": "other-owner"}, {"session_id": "other-session"}):
                with self.subTest(change=change):
                    self.note.clear(); self.note.update(original); self.note.update(change)
                    item = retrieval.retrieve_case_context(CASE, user_id=OWNER, storage_client=self.storage)[0]
                    self.assertEqual(item.summary, "")
                    self.assertEqual(item.confirmed_note, {})
            self.note.clear(); self.note.update(original)
            self.assertEqual(retrieval.retrieve_case_context(CASE, user_id=OWNER, storage_client=self.storage)[0].summary, OLD)


class RecomposeSourceRevisionTests(MemorySourceTestBase):
    def setUp(self):
        super().setUp()
        self.cache_dir = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix="remind-source-cache-")))
        self.stack.enter_context(patch.dict(os.environ, {"RECOMPOSE_CACHE_DIR": str(self.cache_dir)}))
        self.request = RecomposeNoteRequest.model_validate({"session_input": {
            "case_id": CASE, "session_number": 2, "counselor_memo": "Synthetic memo", "transcript_text": "", "persist": False,
        }, "visible_section_ids": ["session_content"]})
        with patch.multiple(settings, enable_rag=False, enable_dense_retrieval=False):
            self.safe = recompose_cache.run_note_pipeline(self.request.session_input, actor=self.actor)
        self.pipeline = self.stack.enter_context(patch.object(recompose_cache, "run_note_pipeline", side_effect=self.result))

    def result(self, *_args, **_kwargs):
        result = self.safe.model_copy(deep=True)
        result.retrieved_case_context = [RetrievedCaseContextItem(source_ref=f"stored_session_note:{SESSION}",
            session_id=SESSION, summary=retrieval._summary_from_note(self.note), confirmed_note=copy.deepcopy(self.note["confirmed_json"]))]
        return result

    def recompose(self):
        return recompose_cache.recompose_note_with_cache(self.request, actor=self.actor)

    def test_fresh_cache_then_source_edit_invalidates_and_unchanged_source_reuses(self):
        first = self.recompose()
        self.assertFalse(first.cache_hit)
        self.assertTrue(self.recompose().cache_hit)
        self.assertEqual(self.pipeline.call_count, 1)
        self.assertEqual(self.confirm({"session_content": NEW}).status_code, 200)
        revised = self.recompose()
        self.assertFalse(revised.cache_hit)
        self.assertNotEqual(revised.cache_key, first.cache_key)
        self.assertEqual(revised.result.retrieved_case_context[0].summary, NEW)
        self.assertTrue(self.recompose().cache_hit)
        self.assertEqual(self.pipeline.call_count, 2)

    def test_source_read_failure_cannot_serve_an_existing_cache_or_generate(self):
        self.recompose()
        with patch.object(SupabaseStorage, "select", side_effect=SupabaseStorageError("SYNTHETIC PRIVATE FAILURE")):
            with self.assertRaisesRegex(RuntimeError, "source") as failure:
                self.recompose()
        self.assertNotIn("SYNTHETIC PRIVATE FAILURE", str(failure.exception))
        self.assertEqual(self.pipeline.call_count, 1)

    def test_source_mutation_during_cache_lookup_is_rejected(self):
        self.recompose()
        original_read = recompose_cache._read_cached_result
        def raced_lookup(key):
            result = original_read(key)
            self.note["confirmed_json"] = {"sections": {"session_content": NEW}}
            return result
        with patch.object(recompose_cache, "_read_cached_result", side_effect=raced_lookup):
            with self.assertRaisesRegex(RuntimeError, "source"):
                self.recompose()
        self.assertEqual(self.pipeline.call_count, 1)

    def test_source_mutation_during_generation_is_not_cached_or_returned(self):
        def raced_pipeline(*args, **kwargs):
            old = self.result()
            self.note["confirmed_json"] = {"sections": {"session_content": NEW}}
            return old
        self.pipeline.side_effect = raced_pipeline
        with self.assertRaisesRegex(RuntimeError, "source"):
            self.recompose()
        self.assertEqual(list(self.cache_dir.iterdir()), [])

    def test_note_addition_deletion_and_draft_edit_change_cache_scope(self):
        original = self.recompose().cache_key
        self.note["confirmation_status"] = "draft"
        self.note["confirmed_json"] = {}
        draft_key = self.recompose().cache_key
        self.assertNotEqual(original, draft_key)
        self.note["draft_json"] = {"session_content": {"text": NEW}}
        self.assertNotEqual(draft_key, self.recompose().cache_key)
        self.store.tables["generated_notes"].append({**copy.deepcopy(self.note), "id": "second-note"})
        added = self.recompose().cache_key
        self.store.tables["generated_notes"] = []
        self.assertNotEqual(added, self.recompose().cache_key)

    def test_non_rag_cache_does_not_require_source_storage(self):
        with patch.object(settings, "enable_rag", False), patch.object(SupabaseStorage, "select", side_effect=AssertionError("Unexpected source read")):
            self.assertFalse(self.recompose().cache_hit)
            self.assertTrue(self.recompose().cache_hit)

    def test_incomplete_source_snapshot_fails_closed(self):
        self.store.tables["generated_notes"].append({**copy.deepcopy(self.note), "id": "second-note"})
        with patch.object(recompose_cache, "SOURCE_REVISION_LIMIT", 1):
            with self.assertRaisesRegex(RuntimeError, "source"):
                self.recompose()
        self.pipeline.assert_not_called()
        self.assertEqual(list(self.cache_dir.iterdir()), [])

    def test_other_owner_and_case_edits_do_not_change_owned_cache(self):
        first = self.recompose()
        self.store.tables["generated_notes"].extend([
            {**copy.deepcopy(self.note), "id": "foreign-note", "user_id": "other-owner"},
            {**copy.deepcopy(self.note), "id": "other-case-note", "case_id": "other-case"},
        ])
        second = self.recompose()
        self.assertTrue(second.cache_hit)
        self.assertEqual(first.cache_key, second.cache_key)

    def test_service_row_cap_cannot_hide_a_later_source_revision(self):
        second = {**copy.deepcopy(self.note), "id": "zz-second-note"}
        self.store.tables["generated_notes"].append(second)
        request = self.store.request
        def one_row_page(method, table, **kwargs):
            if method == "GET" and table == "generated_notes":
                kwargs = {**kwargs, "query": {**kwargs.get("query", {}), "limit": 1}}
            return request(method, table, **kwargs)
        with patch.object(self.store, "request", side_effect=one_row_page):
            first = self.recompose()
            second["confirmed_json"] = {"sections": {"session_content": NEW}}
            revised = self.recompose()
        self.assertFalse(revised.cache_hit)
        self.assertNotEqual(first.cache_key, revised.cache_key)

    def test_recency_and_cache_exclude_same_owner_note_with_wrong_parent_case(self):
        self.note["case_id"] = "synthetic-other-case"
        def actual_recency_pipeline(*_args, **_kwargs):
            result = self.safe.model_copy(deep=True)
            result.retrieved_case_context = retrieval.retrieve_case_context(CASE, user_id=OWNER, storage_client=self.storage)
            return result
        self.pipeline.side_effect = actual_recency_pipeline
        first = self.recompose()
        self.assertEqual(first.result.retrieved_case_context[0].summary, "")
        self.assertEqual(first.result.retrieved_case_context[0].confirmed_note, {})
        self.note["confirmed_json"] = {"sections": {"session_content": NEW}}
        self.assertEqual(retrieval.retrieve_case_context(CASE, user_id=OWNER, storage_client=self.storage)[0].summary, "")
        repeated = self.recompose()
        self.assertTrue(repeated.cache_hit)
        self.assertEqual(repeated.cache_key, first.cache_key)
        self.assertEqual(repeated.result.retrieved_case_context[0].summary, "")
        # Correcting the parent makes the source eligible and invalidates the empty cache.
        self.note["case_id"] = CASE
        corrected = self.recompose()
        self.assertFalse(corrected.cache_hit)
        self.assertEqual(corrected.result.retrieved_case_context[0].summary, NEW)


if __name__ == "__main__":
    unittest.main(verbosity=2)
