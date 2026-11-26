"""Synthetic PoC storage regressions for the protected offline runner."""
import io
import json
import os
import tempfile
import unittest
import zipfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

if os.environ.get("REMIND_POC_OFFLINE") != "1":
    raise unittest.SkipTest("Use the protected PoC offline runner.")

from app.api.security import AuthenticatedActor
from app.core.config import Settings, settings
from app.schemas.document import DocumentExportRequest
from app.schemas.note import ConfirmGeneratedNoteRequest, GenerateNoteResponse, RecomposeNoteRequest, SessionInput
from app.services import recompose_cache, storage_policy, supabase_storage
from app.services.document_export import DocumentExportService
from test_persistence_workflow import MemoryStore


SOURCE = "Synthetic counselor-reviewed input."
SUMMARY = "Synthetic final counseling note."
ACTOR = "11111111-1111-4111-8111-111111111111"


def synthetic_result():
    section = {"text": SUMMARY, "evidence_type": "direct", "source_refs": ["counselor_memo"]}
    return GenerateNoteResponse.model_validate({
        "structured_case_data": {},
        "evidence_mapped_data": {},
        "session_summary_draft": {
            "session_info": {"case_id": "POC-STORAGE", "session_number": 1, "session_date": "2026-11-19"},
            **{name: section for name in (
                "session_theme", "presenting_problem", "session_content", "counselor_intervention",
                "client_response", "reflection", "next_plan",
            )},
        },
        "verification_report": {},
        "document_transform_preview": {"notice": "Synthetic preview"},
        "sanitized_input": {
            "case_id": "POC-STORAGE", "session_number": 1, "session_date": "2026-11-19",
            "counselor_name": "[COUNSELOR]",
            "sources": {"counselor_memo": SOURCE, "transcript_text": ""},
        },
    })


class PoCStorageTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        # Storage minimization contracts start after case permission is granted.
        self.stack.enter_context(patch.object(settings, "processing_authorization_policy", "synthetic-v1"))
        self.stack.enter_context(patch("app.services.processing_authorization._authorization_rpc", return_value=True))
        # Dict patching supports a meaningful red baseline before poc_mode exists.
        self.stack.enter_context(patch.dict(settings.__dict__, {
            "poc_mode": True, "enable_persistence": True, "enable_rag": False,
            "enable_case_memory": False, "save_original_input": True, "save_raw_input": True,
            "retain_derived_cache": True, "use_stub": True,
            "supabase_url": "https://synthetic.invalid",
            "supabase_publishable_key": "synthetic-public-key",
        }))
        self.actor = AuthenticatedActor(ACTOR, "synthetic-user-token", store_original_input=True)
        self.session = SessionInput(
            case_id="POC-STORAGE", session_number=1, session_date="2026-11-19",
            counselor_memo=SOURCE, transcript_text="", persist=True, insight_lens="none",
        )
        self.result = synthetic_result()

    def test_defaults_require_poc_and_disable_original_storage(self):
        self.assertFalse(Settings.model_fields["save_original_input"].default)
        self.assertTrue(Settings.model_fields["poc_mode"].default)

    def test_poc_omits_raw_column_despite_flags_and_account_opt_in(self):
        self.assertIsNone(supabase_storage._session_raw_input(self.session, self.actor))
        policy = storage_policy.note_storage_policy(self.actor)
        self.assertEqual(policy.generated_note_raw_input_mode, "omitted")
        self.assertFalse(policy.save_original_input)
        self.assertFalse(policy.save_raw_input)
        self.assertTrue(policy.account_store_original_input)
        self.assertIn("without raw_input_text", supabase_storage._stored_message(self.actor))
        row = supabase_storage._build_session_row(self.session, self.result, user_id=self.actor)
        self.assertIsNone(row["raw_input_text"])
        self.assertEqual(json.loads(row["sanitized_input_text"])["sources"]["counselor_memo"], SOURCE)

    def test_account_opt_out_and_disabled_persistence_remain_effective(self):
        opted_out = AuthenticatedActor(ACTOR, "synthetic-user-token", store_original_input=False)
        for poc in (False, True):
            with self.subTest(poc=poc), patch.dict(settings.__dict__, {"poc_mode": poc}):
                self.assertIsNone(supabase_storage._session_raw_input(self.session, opted_out))
                self.assertEqual(storage_policy.note_storage_policy(opted_out).generated_note_raw_input_mode, "omitted")
        with patch.object(settings, "enable_persistence", False):
            self.assertEqual(storage_policy.note_storage_policy(self.actor).generated_note_raw_input_mode, "disabled")
            with patch.object(supabase_storage, "_storage_for_actor") as storage:
                self.assertFalse(supabase_storage.persist_generated_note(self.session, self.result, actor=self.actor).stored)
                storage.assert_not_called()

    def test_recomposition_never_reads_or_writes_cache_in_poc(self):
        request = RecomposeNoteRequest(session_input=self.session, visible_section_ids=["session_content"])
        with patch.object(recompose_cache, "run_note_pipeline", return_value=self.result) as generate, \
                patch.object(recompose_cache, "_read_cached_result", return_value=self.result) as read, \
                patch.object(recompose_cache, "_write_cached_result") as write:
            for _ in range(2):
                response = recompose_cache.recompose_note_with_cache(request, actor=self.actor)
                self.assertFalse(response.cache_hit)
                self.assertEqual(response.result, self.result)
            self.assertEqual(generate.call_count, 2)
            read.assert_not_called()
            write.assert_not_called()

    def test_low_level_cache_helpers_do_not_touch_existing_or_new_files_in_poc(self):
        with tempfile.TemporaryDirectory(prefix="remind-poc-cache-") as directory:
            path = Path(directory) / "synthetic-existing.json"
            path.write_text(self.result.model_dump_json(), encoding="utf-8")
            before = path.read_bytes()
            with patch.object(recompose_cache, "_cache_path", return_value=path) as resolve:
                self.assertIsNone(recompose_cache._read_cached_result("synthetic-existing"))
                recompose_cache._write_cached_result("synthetic-existing", self.result)
                resolve.assert_not_called()
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_explicit_non_poc_storage_and_cache_compatibility(self):
        with patch.dict(settings.__dict__, {"poc_mode": False}):
            self.assertIs(json.loads(supabase_storage._session_raw_input(self.session, self.actor))["masked"], False)
            self.assertEqual(storage_policy.note_storage_policy(self.actor).generated_note_raw_input_mode, "original")
            request = RecomposeNoteRequest(session_input=self.session, visible_section_ids=["session_content"])
            with patch.object(recompose_cache, "_read_cached_result", return_value=self.result), \
                    patch.object(recompose_cache, "run_note_pipeline") as generate:
                self.assertTrue(recompose_cache.recompose_note_with_cache(request, actor=self.actor).cache_hit)
                generate.assert_not_called()

    def test_reviewed_save_confirm_reopen_and_export_preserve_final_note(self):
        store = MemoryStore()
        def request(client, method, table, **kwargs):
            self.assertEqual(client.access_token, "synthetic-user-token")
            return store.request(method, table, actor=ACTOR, **kwargs)
        with patch.object(supabase_storage.SupabaseStorage, "_request", request):
            saved = supabase_storage.persist_generated_note(self.session, self.result, actor=self.actor)
            self.assertTrue(saved.stored, saved.message)
            row, = store.tables["sessions"]
            self.assertIsNone(row["raw_input_text"])
            confirmed = supabase_storage.confirm_generated_note(ConfirmGeneratedNoteRequest(
                note_id=saved.note_id, confirmed_note={"sections": {"session_content": SUMMARY}},
                create_case_memory=False,
            ), actor=self.actor)
            self.assertEqual(confirmed.confirmation_status, "confirmed")
            reopened = supabase_storage.fetch_generated_note(saved.note_id, actor=self.actor)
            self.assertEqual(reopened.confirmed_json["sections"]["session_content"], SUMMARY)
            self.assertFalse(reopened.session_input_is_original)
            self.assertEqual(reopened.session_input.counselor_memo, SOURCE)
        document = DocumentExportService().export(DocumentExportRequest(
            format="docx", document_type="session_note", case_id=self.session.case_id, session_number=1,
            title="Synthetic final note", sections=[{
                "id": "summary", "title": "Summary",
                "content": reopened.confirmed_json["sections"]["session_content"],
            }],
        ))
        with zipfile.ZipFile(io.BytesIO(document.content)) as archive:
            self.assertIn(SUMMARY, archive.read("word/document.xml").decode())
