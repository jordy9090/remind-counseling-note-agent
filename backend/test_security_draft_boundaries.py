"""Offline synthetic draft credential and staging-file regression checks."""
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from threading import Barrier
from unittest.mock import Mock, patch

from app.api.security import AuthenticatedActor
from app.core.config import settings
from app.schemas.note import TemporaryDraftRecord, TemporaryDraftSaveRequest
from app.services import draft_store, supabase_store
from app.services.temporary_draft_payload import temporary_draft_payload


class DraftBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix="synthetic-draft-")))
        self.stack.enter_context(patch.dict(os.environ, {"TEMP_DRAFT_DIR": str(self.directory)}))
        self.stack.enter_context(patch.multiple(settings, supabase_url="https://synthetic.invalid",
            supabase_publishable_key=None, supabase_anon_key=None,
            supabase_service_key="synthetic-service-key", supabase_service_role_key="synthetic-service-key"))
        self.actor = AuthenticatedActor("synthetic-owner", "synthetic-user-token")
        self.request = TemporaryDraftSaveRequest(draft_id="draft_synthetic", case_id="synthetic-case",
            session_number=1, form={"counselor_memo": "Synthetic private draft."})
        self.record = TemporaryDraftRecord(**self.request.model_dump(), saved_at="2026-10-13T12:00:00Z")

    def test_authenticated_missing_public_key_fails_without_network_or_disk_fallback(self):
        operations = [lambda: draft_store.save_temporary_draft(self.request, actor=self.actor),
            lambda: draft_store.get_temporary_draft("draft_synthetic", actor=self.actor),
            lambda: draft_store.list_temporary_drafts(actor=self.actor)]
        for operation in operations:
            with self.subTest(operation=operation), patch.object(supabase_store, "urlopen") as network, \
                    patch.object(draft_store, "_write_to_disk") as disk:
                with self.assertRaises(supabase_store.DraftStorageError):
                    operation()
                network.assert_not_called()
                disk.assert_not_called()
        self.assertEqual(list(self.directory.rglob("*")), [])

    def test_direct_authenticated_credentials_never_return_service_bearer(self):
        with self.assertRaises(supabase_store.DraftStorageError):
            supabase_store._credentials(self.actor)

    def test_authenticated_missing_url_also_fails_without_local_fallback(self):
        with patch.object(settings, "supabase_url", None), \
                patch.object(settings, "supabase_publishable_key", "synthetic-public"), \
                patch.object(draft_store, "_write_to_disk") as disk:
            with self.assertRaises(supabase_store.DraftStorageError):
                draft_store.save_temporary_draft(self.request, actor=self.actor)
            disk.assert_not_called()

    def test_public_key_configuration_preserves_authenticated_bearer(self):
        for key_name in ("supabase_publishable_key", "supabase_anon_key"):
            with self.subTest(key=key_name), patch.object(settings, key_name, "synthetic-public"):
                self.assertTrue(supabase_store.configured_for(self.actor))
                self.assertEqual(supabase_store._credentials(self.actor), ("synthetic-public", "synthetic-user-token"))

    def test_explicit_legacy_credentials_and_unconfigured_local_mode_still_work(self):
        self.assertEqual(supabase_store._credentials("local-owner"), ("synthetic-service-key", "synthetic-service-key"))
        with patch.object(settings, "supabase_url", None):
            self.assertFalse(supabase_store.configured_for("local-owner"))
            saved = draft_store.save_temporary_draft(self.request, actor="local-owner")
            loaded = draft_store.get_temporary_draft(saved.draft_id, actor="local-owner")
            self.assertEqual(loaded.form, temporary_draft_payload(self.request.model_dump())["form"])
            self.assertEqual(len(draft_store.list_temporary_drafts(actor="local-owner")), 1)

    def test_replace_failure_preserves_saved_draft_and_removes_staging(self):
        draft_store._write_to_disk(self.record, actor="local-owner")
        path = draft_store._draft_path(self.record.draft_id, actor="local-owner")
        before = path.read_bytes()
        with patch.object(Path, "replace", side_effect=OSError("Synthetic write failure")):
            with self.assertRaises(OSError):
                draft_store._write_to_disk(self.record.model_copy(update={"form": {"text": "new synthetic"}}), actor="local-owner")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(path.parent.iterdir()), [path])

    def test_serialization_failure_leaves_no_staging(self):
        invalid = Mock(draft_id="draft_synthetic")
        invalid.model_dump.side_effect = ValueError("Synthetic serialization failure")
        with self.assertRaises(ValueError):
            draft_store._write_to_disk(invalid, actor="local-owner")
        self.assertEqual(list(self.directory.rglob("*.tmp")), [])

    def test_interrupted_replace_removes_staging(self):
        with patch.object(Path, "replace", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                draft_store._write_to_disk(self.record, actor="local-owner")
        self.assertEqual(list(self.directory.rglob("*.tmp")), [])

    def test_concurrent_writes_have_distinct_staging_and_complete_json(self):
        barrier = Barrier(2)
        seen = []
        replace = Path.replace
        def observed(path, destination):
            seen.append(path)
            return replace(path, destination)
        def write():
            barrier.wait(timeout=5)
            draft_store._write_to_disk(self.record, actor="local-owner")
        with patch.object(Path, "replace", observed), ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(write) for _ in range(2)]
            for future in futures:
                future.result(timeout=10)
        self.assertEqual(len(set(seen)), 2)
        path = draft_store._draft_path(self.record.draft_id, actor="local-owner")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), self.record.model_dump(mode="json"))
        self.assertEqual(list(path.parent.iterdir()), [path])


if __name__ == "__main__":
    unittest.main()
