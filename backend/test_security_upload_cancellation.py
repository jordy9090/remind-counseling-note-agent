"""Synthetic cancellation checks for raw uploads before ownership transfers."""
from __future__ import annotations

import asyncio
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import UploadFile
from starlette.datastructures import Headers

from app.services import upload_validation


class UploadCancellationTests(unittest.IsolatedAsyncioTestCase):
    kind = "document"

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory(prefix="remind-security-cancel-")
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        env = patch.dict(os.environ, {"UPLOAD_TMP_DIR": directory.name})
        env.start()
        self.addCleanup(env.stop)

    def upload(self, kind: str) -> tuple[UploadFile, bytes]:
        content = b"SYNTHETIC-PRIVATE-UPLOAD"
        name, media = "synthetic.txt", "text/plain"
        if kind == "audio":
            content = b"RIFF\x00\x00\x00\x00WAVE" + content
            name, media = "synthetic.wav", "audio/wav"
        return UploadFile(file=io.BytesIO(content), filename=name,
                          headers=Headers({"content-type": media})), content

    async def cancel_at(self, task: asyncio.Task, reached: asyncio.Event) -> None:
        try:
            await asyncio.wait_for(reached.wait(), timeout=2)
            self.assertEqual(len(list(self.directory.iterdir())), 1,
                             "The upload must reach a created raw temporary file")
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(task.cancelled(), "Cancellation must propagate to the caller")
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_cancel_during_read_removes_partial_raw_file(self) -> None:
        upload, _ = self.upload(self.kind)
        original_read = upload.read
        reached = asyncio.Event()
        blocked = asyncio.Event()
        chunks_read = 0

        async def interrupted_read(size: int) -> bytes:
            nonlocal chunks_read
            if chunks_read == 0:
                chunks_read += 1
                return await original_read(size)
            reached.set()
            await blocked.wait()
            return b""

        with patch.object(upload, "read", interrupted_read):
            task = asyncio.create_task(upload_validation.persist_upload_to_temp(upload, self.kind))
            await self.cancel_at(task, reached)
        self.assertEqual(chunks_read, 1)
        self.assertTrue(upload.file.closed)
        self.assertEqual(list(self.directory.iterdir()), [])

    async def test_cancel_during_close_removes_complete_raw_file(self) -> None:
        upload, content = self.upload(self.kind)
        original_close = upload.close
        reached = asyncio.Event()
        blocked = asyncio.Event()

        async def interrupted_close() -> None:
            await original_close()
            self.assertEqual(next(self.directory.iterdir()).read_bytes(), content)
            reached.set()
            await blocked.wait()

        with patch.object(upload, "close", interrupted_close):
            task = asyncio.create_task(upload_validation.persist_upload_to_temp(upload, self.kind))
            await self.cancel_at(task, reached)
        self.assertTrue(upload.file.closed)
        self.assertEqual(list(self.directory.iterdir()), [])

    async def test_close_failure_removes_raw_file_and_propagates_error(self) -> None:
        upload, content = self.upload(self.kind)
        original_close = upload.close
        failure = OSError("Synthetic close failure")

        async def failed_close() -> None:
            await original_close()
            self.assertEqual(next(self.directory.iterdir()).read_bytes(), content)
            raise failure

        with patch.object(upload, "close", failed_close):
            with self.assertRaises(OSError) as raised:
                await upload_validation.persist_upload_to_temp(upload, self.kind)
        self.assertIs(raised.exception, failure)
        self.assertTrue(upload.file.closed)
        self.assertEqual(list(self.directory.iterdir()), [])

    async def test_success_transfers_file_ownership_to_downstream_caller(self) -> None:
        upload, content = self.upload(self.kind)
        result = await upload_validation.persist_upload_to_temp(upload, self.kind)
        self.assertTrue(upload.file.closed)
        self.assertEqual(result.size_bytes, len(content))
        self.assertEqual(result.temp_path.read_bytes(), content)
        self.assertTrue(result.temp_path.is_relative_to(self.directory))
        self.assertEqual(list(self.directory.iterdir()), [result.temp_path])
        upload_validation.cleanup_temp_file(result.temp_path)
        self.assertEqual(list(self.directory.iterdir()), [])


class AudioUploadCancellationTests(UploadCancellationTests):
    kind = "audio"


if __name__ == "__main__":
    unittest.main(verbosity=2)
