"""Synthetic, local-only checks for cache writes and upload cleanup."""
from __future__ import annotations

import asyncio
import io
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier, Event, Lock
from unittest.mock import Mock, patch

from fastapi import UploadFile
from starlette.datastructures import Headers

from app.schemas.note import RecomposeNoteRequest, SessionInput
from app.services import recompose_cache, upload_validation


class RecomposeFileSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory(prefix="remind-security-")
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        env = patch.dict(os.environ, {"RECOMPOSE_CACHE_DIR": directory.name})
        env.start()
        self.addCleanup(env.stop)
        self.key = "a" * 64
        self.result = Mock()
        self.result.model_dump.return_value = {"synthetic": "PRIVATE-SYNTHETIC-CACHE-CONTENT"}

    def test_success_writes_complete_json_without_staging_files(self) -> None:
        recompose_cache._write_cached_result(self.key, self.result)
        path = self.directory / f"{self.key}.json"
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), self.result.model_dump.return_value)
        self.assertEqual(list(self.directory.iterdir()), [path])

    def test_replace_failure_removes_staging_content_and_preserves_previous_cache(self) -> None:
        path = self.directory / f"{self.key}.json"
        path.write_text('{"synthetic": "previous"}', encoding="utf-8")
        with patch.object(Path, "replace", side_effect=OSError("synthetic replace failure")):
            with self.assertRaises(OSError):
                recompose_cache._write_cached_result(self.key, self.result)
        self.assertEqual(path.read_text(encoding="utf-8"), '{"synthetic": "previous"}')
        self.assertEqual(list(self.directory.iterdir()), [path], "Failed writes must not leave plaintext staging files")

    def test_serialization_failure_leaves_no_file(self) -> None:
        self.result.model_dump.side_effect = ValueError("synthetic serialization failure")
        with self.assertRaises(ValueError):
            recompose_cache._write_cached_result(self.key, self.result)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_concurrent_writes_have_separate_staging_files(self) -> None:
        barrier = Barrier(2)
        original_replace = Path.replace
        staged_paths: list[Path] = []

        def synchronized_replace(path, destination):
            staged_paths.append(path)
            return original_replace(path, destination)

        def concurrent_write():
            barrier.wait(timeout=5)
            recompose_cache._write_cached_result(self.key, self.result)

        with patch.object(Path, "replace", synchronized_replace), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(concurrent_write) for _ in range(2)]
            for future in futures:
                future.result(timeout=10)
        self.assertEqual(len(set(staged_paths)), 2)
        self.assertEqual(json.loads((self.directory / f"{self.key}.json").read_text(encoding="utf-8")),
                         self.result.model_dump.return_value)
        self.assertEqual(len(list(self.directory.iterdir())), 1)

    def test_identical_inputs_from_different_actors_have_distinct_cache_keys(self) -> None:
        request = RecomposeNoteRequest(session_input=SessionInput(
            case_id="synthetic-cache-case", session_number=1, session_date="2026-10-13",
            counselor_name="Synthetic counselor", counselor_memo="Synthetic material", transcript_text="",
        ), visible_section_ids=["session_content"])
        key_a = recompose_cache.build_recompose_cache_key(request, actor="synthetic-a")
        key_b = recompose_cache.build_recompose_cache_key(request, actor="synthetic-b")
        self.assertNotEqual(key_a, key_b)
        self.assertNotIn("Synthetic material", key_a)

    def test_destination_replacements_cannot_overlap_in_one_process(self) -> None:
        both_staged, first_entered, release_first, overlap = Event(), Event(), Event(), Event()
        original_file = tempfile.NamedTemporaryFile
        original_replace = Path.replace
        state_lock = Lock()
        staged = 0

        @contextmanager
        def observed_file(*args, **kwargs):
            nonlocal staged
            with original_file(*args, **kwargs) as handle:
                yield handle
            with state_lock:
                staged += 1
                if staged == 2:
                    both_staged.set()

        def observed_replace(path, destination):
            if first_entered.is_set() and not release_first.is_set():
                overlap.set()
            if not first_entered.is_set():
                first_entered.set()
                if not release_first.wait(timeout=5):
                    raise TimeoutError("Synthetic replacement synchronization timeout")
            return original_replace(path, destination)

        with patch.object(tempfile, "NamedTemporaryFile", observed_file), \
                patch.object(Path, "replace", observed_replace), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(recompose_cache._write_cached_result, self.key, self.result)
            try:
                self.assertTrue(first_entered.wait(timeout=5))
                second = pool.submit(recompose_cache._write_cached_result, self.key, self.result)
                self.assertTrue(both_staged.wait(timeout=5))
                self.assertFalse(overlap.wait(timeout=0.1), "Concurrent destination replacements must serialize")
            finally:
                release_first.set()
            first.result(timeout=5)
            second.result(timeout=5)


class UploadCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory(prefix="remind-security-upload-")
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        env = patch.dict(os.environ, {"UPLOAD_TMP_DIR": directory.name, "DOCUMENT_UPLOAD_MAX_BYTES": "64"})
        env.start()
        self.addCleanup(env.stop)

    def upload(self, content: bytes, *, name: str = "synthetic.txt", media: str = "text/plain") -> UploadFile:
        return UploadFile(file=io.BytesIO(content), filename=name, headers=Headers({"content-type": media}))

    def test_valid_upload_is_removed_by_cleanup_and_stream_is_closed(self) -> None:
        upload = self.upload(b"SYNTHETIC-PRIVATE-UPLOAD")
        result = asyncio.run(upload_validation.persist_upload_to_temp(upload, "document"))
        self.assertTrue(upload.file.closed)
        self.assertTrue(result.temp_path.is_relative_to(self.directory))
        self.assertEqual(result.temp_path.read_bytes(), b"SYNTHETIC-PRIVATE-UPLOAD")
        upload_validation.cleanup_temp_file(result.temp_path)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_oversized_upload_is_removed(self) -> None:
        upload = self.upload(b"x" * 65)
        with self.assertRaises(upload_validation.UploadValidationError) as raised:
            asyncio.run(upload_validation.persist_upload_to_temp(upload, "document"))
        self.assertEqual(raised.exception.status_code, 413)
        self.assertTrue(upload.file.closed)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_invalid_signature_is_removed(self) -> None:
        with self.assertRaises(upload_validation.UploadValidationError):
            asyncio.run(upload_validation.persist_upload_to_temp(
                self.upload(b"SYNTHETIC-INVALID-PDF", name="synthetic.pdf", media="application/pdf"), "document"))
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_interrupted_upload_is_removed(self) -> None:
        upload = self.upload(b"synthetic")

        async def interrupted_read(size):
            if not getattr(upload, "first_chunk_read", False):
                upload.first_chunk_read = True
                return b"SYNTHETIC-PARTIAL-UPLOAD"
            raise OSError("synthetic read failure")

        with patch.object(upload, "read", interrupted_read):
            with self.assertRaises(OSError):
                asyncio.run(upload_validation.persist_upload_to_temp(upload, "document"))
        self.assertTrue(upload.file.closed)
        self.assertEqual(list(self.directory.iterdir()), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
