"""Validation helpers for temporary upload processing.

The backend does not persist raw uploads. These helpers only stream the upload
to a temporary file long enough for extraction/transcription services to read it.
"""
from __future__ import annotations

import os
import re
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fastapi import UploadFile


UploadKind = Literal["document", "audio"]

DOCUMENT_MAX_BYTES = 20 * 1024 * 1024
AUDIO_MAX_BYTES = 500 * 1024 * 1024

DOCUMENT_MEDIA_TYPES = {
    ".txt": {"text/plain"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".pdf": {"application/pdf"},
}

AUDIO_MEDIA_TYPES = {
    ".wav": {"audio/wav", "audio/x-wav", "audio/wave"},
    ".mp3": {"audio/mpeg", "audio/mp3"},
    ".m4a": {"audio/mp4", "audio/m4a", "audio/x-m4a"},
}


class UploadValidationError(Exception):
    """Client-facing upload validation error."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class ValidatedUpload:
    filename: str
    media_type: str
    suffix: str
    size_bytes: int
    temp_path: Path


async def persist_upload_to_temp(upload: UploadFile, kind: UploadKind) -> ValidatedUpload:
    """Validate an upload and persist it to a temporary path for downstream parsing."""
    filename = safe_filename(upload.filename or "")
    suffix = Path(filename).suffix.lower()
    allowed_media = media_types_for(kind).get(suffix)
    if not filename or not suffix or allowed_media is None:
        raise UploadValidationError(415, "지원하지 않는 파일 형식입니다.")

    media_type = (upload.content_type or "").split(";")[0].strip().lower()
    if media_type not in allowed_media:
        raise UploadValidationError(415, "파일 확장자와 Content-Type이 일치하지 않습니다.")

    max_bytes = upload_max_bytes(kind)
    temp_path: Path | None = None
    size = 0
    try:
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix,
            prefix=f"remind_{kind}_",
            dir=os.getenv("UPLOAD_TMP_DIR") or None,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise UploadValidationError(413, "업로드 가능한 파일 크기를 초과했습니다.")
                temp_file.write(chunk)
    except Exception:
        if temp_path is not None:
            cleanup_temp_file(temp_path)
        raise
    finally:
        await upload.close()

    if size == 0:
        cleanup_temp_file(temp_path)
        raise UploadValidationError(400, "빈 파일은 업로드할 수 없습니다.")

    if not signature_matches(temp_path, suffix, kind):
        cleanup_temp_file(temp_path)
        raise UploadValidationError(415, "파일 내용이 허용된 형식과 일치하지 않습니다.")

    return ValidatedUpload(
        filename=filename,
        media_type=media_type,
        suffix=suffix,
        size_bytes=size,
        temp_path=temp_path,
    )


def cleanup_temp_file(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def upload_max_bytes(kind: UploadKind) -> int:
    env_name = "DOCUMENT_UPLOAD_MAX_BYTES" if kind == "document" else "AUDIO_UPLOAD_MAX_BYTES"
    default = DOCUMENT_MAX_BYTES if kind == "document" else AUDIO_MAX_BYTES
    raw_value = os.getenv(env_name)
    if not raw_value:
        return default
    try:
        return max(1, int(raw_value))
    except ValueError:
        return default


def media_types_for(kind: UploadKind) -> dict[str, set[str]]:
    return DOCUMENT_MEDIA_TYPES if kind == "document" else AUDIO_MEDIA_TYPES


def safe_filename(filename: str) -> str:
    normalized = unicodedata.normalize("NFC", filename).strip()
    normalized = normalized.replace("\\", "/").split("/")[-1]
    normalized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", normalized)
    normalized = re.sub(r"\s+", "_", normalized).strip("._ ")
    return normalized[:180]


def signature_matches(path: Path, suffix: str, kind: UploadKind) -> bool:
    head = path.read_bytes()[:64]
    if kind == "document":
        if suffix == ".pdf":
            return head.startswith(b"%PDF-")
        if suffix == ".docx":
            return is_docx_zip(path)
        if suffix == ".txt":
            return b"\x00" not in head
    if suffix == ".wav":
        return len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WAVE"
    if suffix == ".mp3":
        return head.startswith(b"ID3") or (len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0)
    if suffix == ".m4a":
        return len(head) >= 12 and head[4:8] == b"ftyp"
    return False


def is_docx_zip(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            return "[Content_Types].xml" in names and "word/document.xml" in names
    except zipfile.BadZipFile:
        return False
