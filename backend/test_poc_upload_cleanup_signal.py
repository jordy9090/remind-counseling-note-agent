"""Synthetic cleanup-failure diagnostics without filenames or upload contents."""
from __future__ import annotations

import asyncio
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

if os.environ.get("REMIND_POC_OFFLINE") != "1":
    raise unittest.SkipTest("Use the protected PoC offline runner.")

from fastapi import UploadFile
from starlette.datastructures import Headers

from app.services import upload_validation


PRIVATE = "SYNTHETIC-PRIVATE-UPLOAD"
SIGNAL = "operation_failed code=temporary_upload_cleanup"


class UploadCleanupSignalTests(unittest.IsolatedAsyncioTestCase):
    def assert_fixed_signal(self, captured):
        self.assertEqual([record.getMessage() for record in captured.records], [SIGNAL])
        for record in captured.records:
            self.assertIsNone(record.exc_info)
            self.assertIsNone(record.stack_info)
            self.assertNotIn(PRIVATE, record.getMessage())

    async def test_unlink_failure_emits_only_a_fixed_operation_code(self):
        with tempfile.TemporaryDirectory(prefix="remind-cleanup-signal-") as directory:
            path = Path(directory, f"{PRIVATE}.txt")
            path.write_text(PRIVATE, encoding="utf-8")
            failure = PermissionError(f"{PRIVATE}: {path}")
            with patch.object(Path, "unlink", side_effect=failure), self.assertLogs("remind.api_errors", "WARNING") as captured:
                self.assertIsNone(upload_validation.cleanup_temp_file(path))
            self.assert_fixed_signal(captured)
            self.assertTrue(path.exists(), "The signal must not claim the failed erasure completed")
            upload_validation.cleanup_temp_file(path)
            self.assertEqual(list(Path(directory).iterdir()), [])

    async def test_normal_missing_and_absent_paths_emit_no_failure_signal(self):
        with tempfile.TemporaryDirectory(prefix="remind-cleanup-control-") as directory:
            path = Path(directory, "synthetic.txt")
            path.write_text(PRIVATE, encoding="utf-8")
            with self.assertNoLogs("remind.api_errors", "WARNING"):
                upload_validation.cleanup_temp_file(path)
                upload_validation.cleanup_temp_file(path)
                upload_validation.cleanup_temp_file(None)
            self.assertEqual(list(Path(directory).iterdir()), [])

    async def test_failed_cleanup_preserves_upload_cancellation_and_closes_the_stream(self):
        for kind, filename, media in (("document", "synthetic.txt", "text/plain"),
                                      ("audio", "synthetic.wav", "audio/wav")):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(prefix="remind-cleanup-cancel-") as directory:
                upload = UploadFile(file=io.BytesIO(), filename=filename, headers=Headers({"content-type": media}))
                cancellation = asyncio.CancelledError()
                with patch.dict(os.environ, {"UPLOAD_TMP_DIR": directory}), \
                        patch.object(upload, "read", AsyncMock(side_effect=[PRIVATE.encode(), cancellation])), \
                        patch.object(Path, "unlink", side_effect=PermissionError(PRIVATE)), \
                        self.assertLogs("remind.api_errors", "WARNING") as captured:
                    with self.assertRaises(asyncio.CancelledError) as caught:
                        await upload_validation.persist_upload_to_temp(upload, kind)
                self.assertIs(caught.exception, cancellation)
                self.assertTrue(upload.file.closed)
                self.assert_fixed_signal(captured)
                paths = list(Path(directory).iterdir())
                self.assertEqual(len(paths), 1)
                upload_validation.cleanup_temp_file(paths[0])
                self.assertEqual(list(Path(directory).iterdir()), [])
