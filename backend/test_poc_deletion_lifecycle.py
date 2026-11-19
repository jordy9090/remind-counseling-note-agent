"""Synthetic client contracts for atomic deletion and late-writer rejection.

Run through tests/run_poc_review.py. No database or external service is used.
The fixture models the database RPC/trigger contract; SQL tests verify real locking.
"""
from __future__ import annotations

import asyncio
import copy
import os
import unittest
from unittest.mock import patch

if os.environ.get("REMIND_POC_OFFLINE") != "1":
    raise unittest.SkipTest("Use the protected PoC offline runner.")

from fastapi import HTTPException, Response

from app.api.routes import notes
from app.api.security import AuthenticatedActor
from app.core.config import settings
from app.services import supabase_storage, transcript_windows
from test_persistence_workflow import MemoryStore


OWNER = "11111111-1111-4111-8111-111111111111"
CASE = "synthetic-delete-case"
SESSION = "synthetic-delete-session"
NOTE = "synthetic-delete-note"
PRIVATE = "SYNTHETIC-PRIVATE-DELETE-INPUT"


class SessionInputDeletionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        scope = {"user_id": OWNER, "case_id": CASE, "session_id": SESSION}
        self.store.tables = {
            "cases": [{"id": CASE, "user_id": OWNER, "counselor_id": OWNER}],
            "sessions": [{"id": SESSION, "user_id": OWNER, "case_id": CASE, "session_number": 1,
                          "raw_input_text": PRIVATE, "sanitized_input_text": PRIVATE}],
            "generated_notes": [{"id": NOTE, **scope, "confirmed_json": {"sections": {"session_content": "Synthetic final note"}}}],
            "transcript_turns": [{"id": "synthetic-turn", **scope, "counselor_id": OWNER,
                                  "turn_index": 0, "speaker_role": "client", "sanitized_text": PRIVATE}],
            "transcript_windows": [{"id": "synthetic-window", **scope, "window_text": PRIVATE}],
        }
        self.actor = AuthenticatedActor(OWNER, "synthetic-token")
        self.client = supabase_storage.SupabaseStorage(access_token="synthetic-token")
        self.note_before = copy.deepcopy(self.store.tables["generated_notes"])
        self.calls = []
        self.fail_after = None
        self.enterContext(patch.multiple(settings, supabase_url="https://synthetic.invalid",
                                        supabase_publishable_key="synthetic-public", enable_dense_retrieval=False))
        self.enterContext(patch.object(supabase_storage, "_storage_for_actor", return_value=self.client))

    def request(self, method, table, **kwargs):
        self.calls.append((method, table))
        if table == "rpc/delete_session_input":
            self.assertEqual(method, "POST")
            self.assertEqual(kwargs["body"], {"p_note_id": NOTE})
            pending = copy.deepcopy(self.store.tables)
            for target in ("transcript_windows", "transcript_turns", "sessions"):
                if target == "sessions":
                    pending[target][0].update(raw_input_text=None, sanitized_input_text=None)
                    pending[target][0].setdefault("input_deleted_at", "2026-11-19T00:00:00Z")
                else:
                    pending[target] = [row for row in pending[target] if row["session_id"] != SESSION]
                if target == self.fail_after:
                    raise supabase_storage.SupabaseStorageError(PRIVATE)
            self.store.tables = pending
            return SESSION
        if method == "POST" and table in {"transcript_turns", "transcript_windows"}:
            if self.store.tables["sessions"][0].get("input_deleted_at"):
                raise supabase_storage.SupabaseStorageError("Session input is unavailable", error_code="23514")
        return self.store.request(method, table, actor=OWNER, **kwargs)

    def test_repeated_deletion_clears_inputs_and_preserves_final_note(self):
        with patch.object(self.client, "_request", side_effect=self.request):
            for _ in range(2):
                result = supabase_storage.delete_session_input(NOTE, actor=self.actor)
                self.assertEqual(result.session_id, SESSION)
                self.assertTrue(any("counseling_drafts" in entry for entry in result.kept))
                self.assertTrue(any("case_memory" in entry for entry in result.kept))
        self.assertIsNone(self.store.tables["sessions"][0]["raw_input_text"])
        self.assertIsNone(self.store.tables["sessions"][0]["sanitized_input_text"])
        self.assertEqual(self.store.tables["transcript_turns"], [])
        self.assertEqual(self.store.tables["transcript_windows"], [])
        self.assertEqual(self.store.tables["generated_notes"], self.note_before)
        self.assertEqual(self.store.tables["sessions"][0]["input_deleted_at"], "2026-11-19T00:00:00Z")
        self.assertEqual(self.calls.count(("POST", "rpc/delete_session_input")), 2)
        self.assertFalse(any(method in {"PATCH", "DELETE"} for method, _ in self.calls))

    def test_failed_atomic_rpc_never_returns_success_or_falls_back_to_partial_deletion(self):
        initial = copy.deepcopy(self.store.tables)
        for failed_step in ("transcript_windows", "transcript_turns", "sessions"):
            self.store.tables = copy.deepcopy(initial)
            self.fail_after = failed_step
            with self.subTest(step=failed_step), patch.object(self.client, "_request", side_effect=self.request):
                with self.assertRaises(HTTPException) as caught:
                    asyncio.run(notes.delete_note_session_input(NOTE, self.actor, Response()))
                self.assertEqual(caught.exception.status_code, 503)
                self.assertNotIn(PRIVATE, str(caught.exception.detail))
                self.assertEqual(self.store.tables, initial)
                self.fail_after = None
                recovered = asyncio.run(notes.delete_note_session_input(NOTE, self.actor, Response()))
                self.assertEqual(recovered.session_id, SESSION)
                self.assertIsNone(self.store.tables["sessions"][0]["raw_input_text"])
                self.assertIsNone(self.store.tables["sessions"][0]["sanitized_input_text"])
                self.assertEqual(self.store.tables["transcript_turns"], [])
                self.assertEqual(self.store.tables["transcript_windows"], [])
                self.assertEqual(self.store.tables["generated_notes"], self.note_before)
        self.assertFalse(any(method in {"PATCH", "DELETE"} for method, _ in self.calls))

    def test_lost_response_after_commit_is_safe_to_retry_without_recreating_input(self):
        lost = False

        def lose_first_receipt(method, table, **kwargs):
            nonlocal lost
            result = self.request(method, table, **kwargs)
            if table == "rpc/delete_session_input" and not lost:
                lost = True
                raise supabase_storage.SupabaseStorageError(PRIVATE)
            return result

        with patch.object(self.client, "_request", side_effect=lose_first_receipt):
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(notes.delete_note_session_input(NOTE, self.actor, Response()))
            self.assertEqual(caught.exception.status_code, 503)
            self.assertNotIn(PRIVATE, str(caught.exception.detail))
            committed = copy.deepcopy(self.store.tables)
            self.assertIsNotNone(committed["sessions"][0]["input_deleted_at"])
            self.assertIsNone(committed["sessions"][0]["raw_input_text"])
            self.assertIsNone(committed["sessions"][0]["sanitized_input_text"])
            self.assertEqual(committed["transcript_turns"], [])
            self.assertEqual(committed["transcript_windows"], [])
            recovered = asyncio.run(notes.delete_note_session_input(NOTE, self.actor, Response()))
            self.assertEqual(recovered.session_id, SESSION)
            self.assertEqual(self.store.tables, committed)
            self.assertEqual(self.store.tables["generated_notes"], self.note_before)
        self.assertEqual(self.calls.count(("POST", "rpc/delete_session_input")), 2)
        self.assertFalse(any(method in {"PATCH", "DELETE"} for method, _ in self.calls))

    def test_inflight_indexing_cannot_recreate_windows_after_successful_deletion(self):
        """Pause at the first window query, after real indexing has loaded turns."""
        deletion = []

        def interleaved_request(method, table, **kwargs):
            if method == "GET" and table == "transcript_windows" and not deletion:
                deletion.append(supabase_storage.delete_session_input(NOTE, actor=self.actor))
                self.assertEqual(self.store.tables["transcript_turns"], [])
                self.assertEqual(self.store.tables["transcript_windows"], [])
                self.assertIsNone(self.store.tables["sessions"][0]["sanitized_input_text"])
            return self.request(method, table, **kwargs)

        with patch.object(self.client, "_request", side_effect=interleaved_request):
            with self.assertRaises(supabase_storage.SupabaseStorageError) as caught:
                transcript_windows.index_transcript_windows(
                    user_id=OWNER, counselor_id=OWNER, case_id=CASE, session_id=SESSION, storage_client=self.client,
                )
            self.assertEqual(caught.exception.error_code, "23514")
        self.assertEqual(len(deletion), 1, "The interleaving must exercise a successful deletion")
        self.assertEqual(self.store.tables["generated_notes"], self.note_before)
        self.assertEqual(self.store.tables["transcript_windows"], [],
                         "An in-flight source snapshot must not recreate deleted transcript windows")

    def test_missing_or_mismatched_rpc_confirmation_is_not_success(self):
        for returned in (None, [], "", "synthetic-other-session"):
            with self.subTest(result=returned), patch.object(self.client, "_request", side_effect=self.request), \
                    patch.object(self.client, "rpc", return_value=returned):
                with self.assertRaises(supabase_storage.SupabaseStorageError):
                    supabase_storage.delete_session_input(NOTE, actor=self.actor)
        self.assertEqual(self.store.tables["sessions"][0]["raw_input_text"], PRIVATE)
