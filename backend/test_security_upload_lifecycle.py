"""Synthetic checks for upload ownership during final validation."""
from __future__ import annotations

import asyncio
import io
import os
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi import UploadFile
from starlette.datastructures import Headers

from app.services import upload_validation


DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def synthetic_docx(*, invalid_filename: bool = False) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("[Content_Types].xml", "<synthetic/>")
        archive.writestr("word/document.xml", "<synthetic>PRIVATE-UPLOAD</synthetic>")
    content = bytearray(stream.getvalue())
    if invalid_filename:
        central = content.index(b"PK\x01\x02")
        flags = struct.unpack_from("<H", content, central + 8)[0]
        struct.pack_into("<H", content, central + 8, flags | 0x800)
        content[central + 46] = 0xFF
    return bytes(content)


class UploadValidationLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory(prefix="remind-validation-lifecycle-")
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        env = patch.dict(os.environ, {"UPLOAD_TMP_DIR": directory.name})
        env.start()
        self.addCleanup(env.stop)

    def upload(self, content: bytes, name: str = "synthetic.docx", media: str = DOCX_MEDIA) -> UploadFile:
        return UploadFile(file=io.BytesIO(content), filename=name, headers=Headers({"content-type": media}))

    async def test_invalid_utf8_zip_filename_removes_raw_file(self) -> None:
        upload = self.upload(synthetic_docx(invalid_filename=True))
        with self.assertRaises(UnicodeDecodeError):
            await upload_validation.persist_upload_to_temp(upload, "document")
        self.assertTrue(upload.file.closed)
        self.assertEqual(list(self.directory.iterdir()), [], "Failed archive parsing must not retain raw upload bytes")

    async def test_signature_reader_failures_remove_file_and_preserve_error(self) -> None:
        for failure in (OSError("Synthetic read failure"), asyncio.CancelledError("Synthetic interruption")):
            with self.subTest(error=type(failure).__name__):
                upload = self.upload(b"SYNTHETIC-PRIVATE-TEXT", "synthetic.txt", "text/plain")
                with patch.object(upload_validation, "signature_matches", side_effect=failure):
                    with self.assertRaises(type(failure)) as raised:
                        await upload_validation.persist_upload_to_temp(upload, "document")
                self.assertIs(raised.exception, failure)
                self.assertTrue(upload.file.closed)
                self.assertEqual(list(self.directory.iterdir()), [])

    async def test_archive_reader_failures_remove_file_and_preserve_error(self) -> None:
        for failure in (OSError("Synthetic archive failure"), asyncio.CancelledError("Synthetic interruption")):
            with self.subTest(error=type(failure).__name__):
                upload = self.upload(synthetic_docx())
                with patch.object(upload_validation, "validate_docx_archive_limits", side_effect=failure):
                    with self.assertRaises(type(failure)) as raised:
                        await upload_validation.persist_upload_to_temp(upload, "document")
                self.assertIs(raised.exception, failure)
                self.assertTrue(upload.file.closed)
                self.assertEqual(list(self.directory.iterdir()), [])

    async def test_expected_validation_statuses_remain_unchanged(self) -> None:
        for content, name, media, status in (
            (b"", "empty.txt", "text/plain", 400),
            (b"\x00not-text", "binary.txt", "text/plain", 415),
            (b"PKnot-a-zip", "broken.docx", DOCX_MEDIA, 422),
        ):
            with self.subTest(name=name):
                upload = self.upload(content, name, media)
                with self.assertRaises(upload_validation.UploadValidationError) as raised:
                    await upload_validation.persist_upload_to_temp(upload, "document")
                self.assertEqual(raised.exception.status_code, status)
                self.assertTrue(upload.file.closed)
                self.assertEqual(list(self.directory.iterdir()), [])

    async def test_successful_document_and_audio_transfer_ownership(self) -> None:
        for content, name, media, kind in (
            (b"SYNTHETIC-PRIVATE-TEXT", "synthetic.txt", "text/plain", "document"),
            (synthetic_docx(), "synthetic.docx", DOCX_MEDIA, "document"),
            (b"RIFF\x00\x00\x00\x00WAVESYNTHETIC", "synthetic.wav", "audio/wav", "audio"),
        ):
            with self.subTest(name=name):
                upload = self.upload(content, name, media)
                result = await upload_validation.persist_upload_to_temp(upload, kind)
                self.assertEqual(result.temp_path.read_bytes(), content)
                self.assertTrue(upload.file.closed)
                upload_validation.cleanup_temp_file(result.temp_path)
                self.assertEqual(list(self.directory.iterdir()), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
